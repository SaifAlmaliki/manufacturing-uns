import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Factory, GitBranch, Plus, Trash2 } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { useUNS } from '../../context/UNSContext';
import { joinSegments, validateSegment } from '../../lib/uns/topics';
import { unsGraphQLClient } from '../../services/graphql/client';
import type {
  GraphqlHierarchyMigrateJob,
  GraphqlHierarchyTree,
  GraphqlPrefixRenameInput,
} from '../../services/graphql/types';
import { AccessRestricted } from '../common/AccessRestricted';
import {
  BtnGhost,
  BtnPrimary,
  BtnSecondary,
  CompactKpiRow,
  ConsoleCard,
  ConsoleInput,
  PageContent,
  PageShell,
  PageStat,
} from '../ui/console-ui';

type NodeLevel = 'enterprise' | 'site' | 'area' | 'line' | 'cell';

type NodeRef =
  | { level: 'enterprise' }
  | { level: 'site'; site: number }
  | { level: 'area'; site: number; area: number }
  | { level: 'line'; site: number; area: number; line: number }
  | { level: 'cell'; site: number; area: number; line: number; cell: number };

const CHILD_LEVEL: Record<NodeLevel, NodeLevel | null> = {
  enterprise: 'site',
  site: 'area',
  area: 'line',
  line: 'cell',
  cell: null,
};

const CHILD_BASE_NAME: Record<Exclude<NodeLevel, 'enterprise'>, string> = {
  site: 'Site',
  area: 'Area',
  line: 'Line',
  cell: 'Cell',
};

const LEVEL_LABEL: Record<NodeLevel, string> = {
  enterprise: 'Enterprise',
  site: 'Site',
  area: 'Area',
  line: 'Line',
  cell: 'Cell',
};

const SIMULATOR_BANNER =
  'The simulator still publishes the shipped WTP paths. Renamed nodes will not match live simulator topics until the publisher is retargeted. The old graph branch reappears while anything still publishes the old prefix; the graph rename is durable only after the publisher is retargeted.';

function cloneTree(tree: GraphqlHierarchyTree): GraphqlHierarchyTree {
  return {
    enterprise: tree.enterprise,
    sites: tree.sites.map((site) => ({
      name: site.name,
      areas: site.areas.map((area) => ({
        name: area.name,
        kind: area.kind,
        lines: area.lines.map((line) => ({
          name: line.name,
          cells: [...line.cells],
        })),
      })),
    })),
  };
}

function nodeName(tree: GraphqlHierarchyTree, ref: NodeRef): string {
  switch (ref.level) {
    case 'enterprise':
      return tree.enterprise;
    case 'site':
      return tree.sites[ref.site].name;
    case 'area':
      return tree.sites[ref.site].areas[ref.area].name;
    case 'line':
      return tree.sites[ref.site].areas[ref.area].lines[ref.line].name;
    case 'cell':
      return tree.sites[ref.site].areas[ref.area].lines[ref.line].cells[ref.cell];
  }
}

function nodePrefix(tree: GraphqlHierarchyTree, ref: NodeRef): string {
  const enterprise = tree.enterprise;
  if (ref.level === 'enterprise') return enterprise;
  const site = tree.sites[ref.site].name;
  if (ref.level === 'site') return joinSegments(enterprise, site);
  const area = tree.sites[ref.site].areas[ref.area].name;
  if (ref.level === 'area') return joinSegments(enterprise, site, area);
  const line = tree.sites[ref.site].areas[ref.area].lines[ref.line].name;
  if (ref.level === 'line') return joinSegments(enterprise, site, area, line);
  const cell = tree.sites[ref.site].areas[ref.area].lines[ref.line].cells[ref.cell];
  return joinSegments(enterprise, site, area, line, cell);
}

function siblingNames(tree: GraphqlHierarchyTree, ref: NodeRef): string[] {
  switch (ref.level) {
    case 'enterprise':
      return [];
    case 'site':
      return tree.sites.filter((_, i) => i !== ref.site).map((s) => s.name);
    case 'area': {
      const areas = tree.sites[ref.site].areas;
      return areas.filter((_, i) => i !== ref.area).map((a) => a.name);
    }
    case 'line': {
      const lines = tree.sites[ref.site].areas[ref.area].lines;
      return lines.filter((_, i) => i !== ref.line).map((l) => l.name);
    }
    case 'cell': {
      const cells = tree.sites[ref.site].areas[ref.area].lines[ref.line].cells;
      return cells.filter((_, i) => i !== ref.cell);
    }
  }
}

function uniqueChildName(existing: string[], base: string): string {
  if (!existing.includes(base)) return base;
  let n = 2;
  while (existing.includes(`${base}${n}`)) n += 1;
  return `${base}${n}`;
}

function applyName(tree: GraphqlHierarchyTree, ref: NodeRef, name: string): GraphqlHierarchyTree {
  const next = cloneTree(tree);
  switch (ref.level) {
    case 'enterprise':
      next.enterprise = name;
      break;
    case 'site':
      next.sites[ref.site].name = name;
      break;
    case 'area':
      next.sites[ref.site].areas[ref.area].name = name;
      break;
    case 'line':
      next.sites[ref.site].areas[ref.area].lines[ref.line].name = name;
      break;
    case 'cell':
      next.sites[ref.site].areas[ref.area].lines[ref.line].cells[ref.cell] = name;
      break;
  }
  return next;
}

function addChild(
  tree: GraphqlHierarchyTree,
  ref: NodeRef,
): { tree: GraphqlHierarchyTree; child: NodeRef } | null {
  const nextLevel = CHILD_LEVEL[ref.level];
  if (!nextLevel) return null;
  const next = cloneTree(tree);
  const base = CHILD_BASE_NAME[nextLevel];
  switch (ref.level) {
    case 'enterprise': {
      const name = uniqueChildName(next.sites.map((s) => s.name), base);
      next.sites.push({ name, areas: [] });
      return { tree: next, child: { level: 'site', site: next.sites.length - 1 } };
    }
    case 'site': {
      const areas = next.sites[ref.site].areas;
      const name = uniqueChildName(areas.map((a) => a.name), base);
      areas.push({ name, kind: 'production', lines: [] });
      return { tree: next, child: { level: 'area', site: ref.site, area: areas.length - 1 } };
    }
    case 'area': {
      const lines = next.sites[ref.site].areas[ref.area].lines;
      const name = uniqueChildName(lines.map((l) => l.name), base);
      lines.push({ name, cells: [] });
      return {
        tree: next,
        child: { level: 'line', site: ref.site, area: ref.area, line: lines.length - 1 },
      };
    }
    case 'line': {
      const cells = next.sites[ref.site].areas[ref.area].lines[ref.line].cells;
      const name = uniqueChildName(cells, base);
      cells.push(name);
      return {
        tree: next,
        child: {
          level: 'cell',
          site: ref.site,
          area: ref.area,
          line: ref.line,
          cell: cells.length - 1,
        },
      };
    }
    case 'cell':
      return null;
  }
}

function parentRef(ref: NodeRef): NodeRef | null {
  switch (ref.level) {
    case 'enterprise':
      return null;
    case 'site':
      return { level: 'enterprise' };
    case 'area':
      return { level: 'site', site: ref.site };
    case 'line':
      return { level: 'area', site: ref.site, area: ref.area };
    case 'cell':
      return { level: 'line', site: ref.site, area: ref.area, line: ref.line };
  }
}

function removeNode(tree: GraphqlHierarchyTree, ref: NodeRef): GraphqlHierarchyTree | null {
  if (ref.level === 'enterprise') return null;
  const next = cloneTree(tree);
  switch (ref.level) {
    case 'site':
      next.sites.splice(ref.site, 1);
      break;
    case 'area':
      next.sites[ref.site].areas.splice(ref.area, 1);
      break;
    case 'line':
      next.sites[ref.site].areas[ref.area].lines.splice(ref.line, 1);
      break;
    case 'cell':
      next.sites[ref.site].areas[ref.area].lines[ref.line].cells.splice(ref.cell, 1);
      break;
  }
  return next;
}

function isPrefixOf(parent: string, child: string): boolean {
  return child === parent || child.startsWith(`${parent}/`);
}

function rebasePrefix(prefix: string, oldAncestor: string, newAncestor: string): string {
  if (prefix === oldAncestor) return newAncestor;
  if (isPrefixOf(oldAncestor, prefix)) {
    return `${newAncestor}${prefix.slice(oldAncestor.length)}`;
  }
  return prefix;
}

function recordRename(
  renames: GraphqlPrefixRenameInput[],
  oldPrefix: string,
  newPrefix: string,
): GraphqlPrefixRenameInput[] {
  if (oldPrefix === newPrefix) return renames;
  let next = [...renames];
  const chained = next.findIndex((r) => r.newPrefix === oldPrefix);
  if (chained >= 0) {
    if (next[chained].oldPrefix === newPrefix) {
      next.splice(chained, 1);
    } else {
      next[chained] = { ...next[chained], newPrefix };
    }
    return next.filter((r) => r.oldPrefix !== r.newPrefix);
  }
  const sameOld = next.findIndex((r) => r.oldPrefix === oldPrefix);
  if (sameOld >= 0) {
    next[sameOld] = { oldPrefix, newPrefix };
    return next.filter((r) => r.oldPrefix !== r.newPrefix);
  }
  next = next
    .map((r) => {
      if (isPrefixOf(oldPrefix, r.oldPrefix) || isPrefixOf(oldPrefix, r.newPrefix)) {
        return {
          oldPrefix: rebasePrefix(r.oldPrefix, oldPrefix, newPrefix),
          newPrefix: rebasePrefix(r.newPrefix, oldPrefix, newPrefix),
        };
      }
      return r;
    })
    .filter((r) => r.oldPrefix !== r.newPrefix)
    .filter(
      (r) =>
        !isPrefixOf(oldPrefix, r.oldPrefix) &&
        !isPrefixOf(newPrefix, r.oldPrefix) &&
        !isPrefixOf(r.oldPrefix, oldPrefix),
    );
  next.push({ oldPrefix, newPrefix });
  return next;
}

function dropRenamesUnder(renames: GraphqlPrefixRenameInput[], prefix: string): GraphqlPrefixRenameInput[] {
  return renames.filter((r) => !isPrefixOf(prefix, r.oldPrefix) && !isPrefixOf(prefix, r.newPrefix));
}

function treeCounts(tree: GraphqlHierarchyTree): { sites: number; areas: number; lines: number; cells: number } {
  let areas = 0;
  let lines = 0;
  let cells = 0;
  for (const site of tree.sites) {
    areas += site.areas.length;
    for (const area of site.areas) {
      lines += area.lines.length;
      for (const line of area.lines) {
        cells += line.cells.length;
      }
    }
  }
  return { sites: tree.sites.length, areas, lines, cells };
}

function validateEditableTree(tree: GraphqlHierarchyTree): string | null {
  try {
    validateSegment(tree.enterprise);
  } catch (err) {
    return err instanceof Error ? err.message : 'Enterprise name is invalid';
  }
  const siteNames = new Set<string>();
  for (const site of tree.sites) {
    try {
      validateSegment(site.name);
    } catch (err) {
      return err instanceof Error ? err.message : 'Site name is invalid';
    }
    if (siteNames.has(site.name)) return `duplicate site under ${tree.enterprise}: ${site.name}`;
    siteNames.add(site.name);
    const areaNames = new Set<string>();
    for (const area of site.areas) {
      try {
        validateSegment(area.name);
      } catch (err) {
        return err instanceof Error ? err.message : 'Area name is invalid';
      }
      if (areaNames.has(area.name)) return `duplicate area under ${site.name}: ${area.name}`;
      areaNames.add(area.name);
      const lineNames = new Set<string>();
      for (const line of area.lines) {
        try {
          validateSegment(line.name);
        } catch (err) {
          return err instanceof Error ? err.message : 'Line name is invalid';
        }
        if (lineNames.has(line.name)) return `duplicate line under ${area.name}: ${line.name}`;
        lineNames.add(line.name);
        const cellNames = new Set<string>();
        for (const cell of line.cells) {
          try {
            validateSegment(cell);
          } catch (err) {
            return err instanceof Error ? err.message : 'Cell name is invalid';
          }
          if (cellNames.has(cell)) return `duplicate cell under ${line.name}: ${cell}`;
          cellNames.add(cell);
        }
      }
    }
  }
  return null;
}

function refsEqual(a: NodeRef | null, b: NodeRef | null): boolean {
  if (!a || !b) return a === b;
  if (a.level !== b.level) return false;
  if (a.level === 'enterprise' || b.level === 'enterprise') return true;
  if (a.site !== b.site) return false;
  if (a.level === 'site' || b.level === 'site') return true;
  if (a.area !== b.area) return false;
  if (a.level === 'area' || b.level === 'area') return true;
  if (a.line !== b.line) return false;
  if (a.level === 'line' || b.level === 'line') return true;
  return a.cell === b.cell;
}

function TreeNodeButton({
  tree,
  nodeRef,
  selected,
  onSelect,
}: {
  tree: GraphqlHierarchyTree;
  nodeRef: NodeRef;
  selected: NodeRef | null;
  onSelect: (ref: NodeRef) => void;
}) {
  const name = nodeName(tree, nodeRef);
  const active = refsEqual(selected, nodeRef);
  const indent =
    nodeRef.level === 'enterprise'
      ? 0
      : nodeRef.level === 'site'
        ? 1
        : nodeRef.level === 'area'
          ? 2
          : nodeRef.level === 'line'
            ? 3
            : 4;
  return (
    <button
      type="button"
      aria-label={`${LEVEL_LABEL[nodeRef.level]} ${name}`}
      aria-current={active ? 'true' : undefined}
      onClick={() => onSelect(nodeRef)}
      className={`flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm transition-colors ${
        active ? 'bg-[#FF7A00] text-white' : 'text-foreground hover:bg-muted hover:text-foreground'
      }`}
      style={{ paddingLeft: `${8 + indent * 12}px` }}
    >
      <span className={`text-[10px] uppercase tracking-wider ${active ? 'text-white/70' : 'text-muted-foreground'}`}>
        {LEVEL_LABEL[nodeRef.level][0]}
      </span>
      <span className="truncate font-medium">{name}</span>
    </button>
  );
}

export const HierarchyView: React.FC = () => {
  const { hasPermission } = useAuth();
  const canEdit = hasPermission('settings_edit');
  const { updateSettings } = useUNS();

  const [tree, setTree] = useState<GraphqlHierarchyTree | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selected, setSelected] = useState<NodeRef | null>(null);
  const [draftName, setDraftName] = useState('');
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [renames, setRenames] = useState<GraphqlPrefixRenameInput[]>([]);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [job, setJob] = useState<GraphqlHierarchyMigrateJob | null>(null);
  const [retrying, setRetrying] = useState(false);

  useEffect(() => {
    if (!canEdit) return;
    let cancelled = false;
    void unsGraphQLClient.getHierarchy().then((next) => {
      if (cancelled) return;
      if (!next) {
        setLoadError('The plant hierarchy could not be loaded.');
        setTree(null);
        return;
      }
      setTree(next);
      setSelected({ level: 'enterprise' });
      setDraftName(next.enterprise);
      setLoadError(null);
    });
    return () => {
      cancelled = true;
    };
  }, [canEdit]);

  const applyDraft = useCallback((): { tree: GraphqlHierarchyTree; renames: GraphqlPrefixRenameInput[] } | null => {
    if (!tree || !selected) return tree ? { tree, renames } : null;
    const current = nodeName(tree, selected);
    const nextName = draftName.trim();
    if (nextName === current) {
      setFieldError(null);
      return { tree, renames };
    }
    try {
      validateSegment(nextName);
    } catch (err) {
      setFieldError(err instanceof Error ? err.message : 'Invalid name');
      return null;
    }
    if (siblingNames(tree, selected).includes(nextName)) {
      setFieldError('Name already used by a sibling');
      return null;
    }
    const oldPrefix = nodePrefix(tree, selected);
    const nextTree = applyName(tree, selected, nextName);
    const newPrefix = nodePrefix(nextTree, selected);
    const nextRenames = recordRename(renames, oldPrefix, newPrefix);
    setTree(nextTree);
    setRenames(nextRenames);
    setDirty(true);
    setFieldError(null);
    return { tree: nextTree, renames: nextRenames };
  }, [tree, selected, draftName, renames]);

  const selectNode = (ref: NodeRef) => {
    if (selected && !refsEqual(selected, ref)) {
      const committed = applyDraft();
      if (!committed) return;
      setSelected(ref);
      setDraftName(nodeName(committed.tree, ref));
      setFieldError(null);
      return;
    }
    if (!tree) return;
    setSelected(ref);
    setDraftName(nodeName(tree, ref));
    setFieldError(null);
  };

  const handleAddChild = () => {
    if (!selected) return;
    const committed = applyDraft();
    if (!committed) return;
    const result = addChild(committed.tree, selected);
    if (!result) return;
    setTree(result.tree);
    setSelected(result.child);
    setDraftName(nodeName(result.tree, result.child));
    setDirty(true);
    setFieldError(null);
  };

  const handleRemove = () => {
    if (!tree || !selected || selected.level === 'enterprise') return;
    const committed = applyDraft();
    if (!committed) return;
    const removedPrefix = nodePrefix(committed.tree, selected);
    const parent = parentRef(selected);
    const next = removeNode(committed.tree, selected);
    if (!next || !parent) return;
    setTree(next);
    setRenames(dropRenamesUnder(committed.renames, removedPrefix));
    setSelected(parent);
    setDraftName(nodeName(next, parent));
    setDirty(true);
    setFieldError(null);
  };

  const handleSave = async () => {
    const committed = applyDraft();
    if (!committed) return;
    const invalid = validateEditableTree(committed.tree);
    if (invalid) {
      setSaveError(invalid);
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      const result = await unsGraphQLClient.saveHierarchy(committed.tree, committed.renames);
      setTree(result.tree);
      setRenames([]);
      setDirty(false);
      setJob(result.job);
      if (selected) {
        setDraftName(nodeName(result.tree, selected));
      }
      updateSettings({ organization: result.tree.enterprise });
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Hierarchy was not saved');
    } finally {
      setSaving(false);
    }
  };

  const handleRetry = async () => {
    setRetrying(true);
    setSaveError(null);
    try {
      const nextJob = await unsGraphQLClient.retryHierarchyMigrate();
      setJob(nextJob);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Hierarchy migrate retry failed');
    } finally {
      setRetrying(false);
    }
  };

  const counts = useMemo(() => (tree ? treeCounts(tree) : null), [tree]);
  const childLevel = selected ? CHILD_LEVEL[selected.level] : null;
  const jobFailed = job?.status === 'failed';
  const draftDirty = Boolean(tree && selected && draftName.trim() !== nodeName(tree, selected));
  const canSave = Boolean(tree) && !saving && (dirty || draftDirty);

  if (!canEdit) {
    return (
      <PageShell id="hierarchy-view" scroll={false} className="flex flex-col font-mono">
        <AccessRestricted featureKey="settings_edit" />
      </PageShell>
    );
  }

  return (
    <PageShell id="hierarchy-view" scroll={false} className="flex flex-col font-mono">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <PageContent fullWidth className="flex min-h-full flex-col gap-3 pb-4">
          <CompactKpiRow
            actions={
              <BtnPrimary onClick={() => void handleSave()} disabled={!canSave}>
                {saving ? 'Saving…' : 'Save'}
              </BtnPrimary>
            }
          >
            <PageStat compact label="Sites" value={counts?.sites ?? '—'} icon={<Factory className="size-3.5 text-muted-foreground" />} />
            <PageStat compact label="Areas" value={counts?.areas ?? '—'} icon={<GitBranch className="size-3.5 text-muted-foreground" />} />
            <PageStat compact label="Lines" value={counts?.lines ?? '—'} icon={<GitBranch className="size-3.5 text-muted-foreground" />} />
            <PageStat compact label="Cells" value={counts?.cells ?? '—'} icon={<GitBranch className="size-3.5 text-muted-foreground" />} />
          </CompactKpiRow>

          <div className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
            {SIMULATOR_BANNER}
          </div>

          {job && (
            <div
              className={`flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2 text-xs ${
                jobFailed
                  ? 'border-rose-300 bg-rose-50 text-rose-800 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200'
                  : job.status === 'done'
                    ? 'border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200'
                    : 'border-border bg-muted/60 text-foreground'
              }`}
            >
              <span>
                Migrate job: <span className="font-semibold">{job.status}</span>
                {job.oldPrefix && job.newPrefix ? (
                  <span className="ml-2 font-mono text-[11px]">
                    {job.oldPrefix} → {job.newPrefix}
                  </span>
                ) : null}
                {job.error ? <span className="ml-2">{job.error}</span> : null}
              </span>
              {jobFailed && (
                <BtnSecondary onClick={() => void handleRetry()} disabled={retrying} className="px-2.5 py-1 text-xs">
                  {retrying ? 'Retrying…' : 'Retry'}
                </BtnSecondary>
              )}
            </div>
          )}

          {saveError && (
            <div className="rounded-lg border border-rose-300 bg-rose-50 px-3 py-2 text-xs text-rose-800 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200">
              {saveError}
            </div>
          )}

          {loadError && (
            <ConsoleCard padding="md" className="text-sm text-muted-foreground">
              {loadError}
            </ConsoleCard>
          )}

          {!loadError && !tree && (
            <ConsoleCard padding="md" className="text-sm text-muted-foreground">
              Loading plant hierarchy…
            </ConsoleCard>
          )}

          {tree && (
            <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(16rem,22rem)]">
              <ConsoleCard padding="none" className="min-h-[280px] overflow-hidden">
                <div className="border-b border-border px-3 py-2 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                  Plant tree
                </div>
                <div className="max-h-[calc(100vh-22rem)] space-y-0.5 overflow-y-auto p-2">
                  <TreeNodeButton tree={tree} nodeRef={{ level: 'enterprise' }} selected={selected} onSelect={selectNode} />
                  {tree.sites.map((site, siteIdx) => (
                    <React.Fragment key={`site-${siteIdx}`}>
                      <TreeNodeButton
                        tree={tree}
                        nodeRef={{ level: 'site', site: siteIdx }}
                        selected={selected}
                        onSelect={selectNode}
                      />
                      {site.areas.map((area, areaIdx) => (
                        <React.Fragment key={`area-${siteIdx}-${areaIdx}`}>
                          <TreeNodeButton
                            tree={tree}
                            nodeRef={{ level: 'area', site: siteIdx, area: areaIdx }}
                            selected={selected}
                            onSelect={selectNode}
                          />
                          {area.lines.map((line, lineIdx) => (
                            <React.Fragment key={`line-${siteIdx}-${areaIdx}-${lineIdx}`}>
                              <TreeNodeButton
                                tree={tree}
                                nodeRef={{ level: 'line', site: siteIdx, area: areaIdx, line: lineIdx }}
                                selected={selected}
                                onSelect={selectNode}
                              />
                              {line.cells.map((cell, cellIdx) => (
                                <TreeNodeButton
                                  key={`cell-${siteIdx}-${areaIdx}-${lineIdx}-${cellIdx}-${cell}`}
                                  tree={tree}
                                  nodeRef={{
                                    level: 'cell',
                                    site: siteIdx,
                                    area: areaIdx,
                                    line: lineIdx,
                                    cell: cellIdx,
                                  }}
                                  selected={selected}
                                  onSelect={selectNode}
                                />
                              ))}
                            </React.Fragment>
                          ))}
                        </React.Fragment>
                      ))}
                    </React.Fragment>
                  ))}
                </div>
              </ConsoleCard>

              <ConsoleCard padding="md" className="space-y-3">
                {selected ? (
                  <>
                    <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                      {LEVEL_LABEL[selected.level]}
                    </div>
                    <label className="block space-y-1.5">
                      <span className="text-xs font-medium text-muted-foreground">Name</span>
                      <ConsoleInput
                        value={draftName}
                        onChange={(e) => setDraftName(e.target.value)}
                        onBlur={() => {
                          applyDraft();
                        }}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.preventDefault();
                            applyDraft();
                          }
                        }}
                        aria-invalid={fieldError ? true : undefined}
                      />
                    </label>
                    {fieldError && <p className="text-xs text-rose-400">{fieldError}</p>}
                    <p className="font-mono text-[11px] text-muted-foreground">{nodePrefix(tree, selected)}</p>
                    <div className="flex flex-wrap gap-2 pt-1">
                      <BtnSecondary onClick={handleAddChild} disabled={!childLevel} title={childLevel ? `Add ${LEVEL_LABEL[childLevel].toLowerCase()}` : 'A cell is a leaf'}>
                        <Plus className="size-3.5" />
                        Add child
                      </BtnSecondary>
                      <BtnGhost
                        onClick={handleRemove}
                        disabled={selected.level === 'enterprise'}
                        className="text-rose-400 hover:text-rose-300"
                      >
                        <Trash2 className="size-3.5" />
                        Remove
                      </BtnGhost>
                    </div>
                  </>
                ) : (
                  <p className="text-sm text-muted-foreground">Select a node in the tree.</p>
                )}
              </ConsoleCard>
            </div>
          )}
        </PageContent>
      </div>
    </PageShell>
  );
};

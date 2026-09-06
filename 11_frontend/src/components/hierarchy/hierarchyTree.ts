import type { GraphqlHierarchyTree } from '../../services/graphql/types';
import { type NodeLevel, levelDef, remainingChildren } from './hierarchyLevels';

export type NodeRef =
  | { level: 'enterprise' }
  | { level: 'site'; site: number }
  | { level: 'area'; site: number; area: number }
  | { level: 'line'; site: number; area: number; line: number }
  | { level: 'cell'; site: number; area: number; line: number; cell: number }
  | { level: 'machine'; site: number; area: number; line: number; cell: number; machine: number };

export function cloneTree(tree: GraphqlHierarchyTree): GraphqlHierarchyTree {
  return {
    enterprise: tree.enterprise,
    sites: tree.sites.map((site) => ({
      name: site.name,
      areas: site.areas.map((area) => ({
        name: area.name,
        kind: area.kind,
        lines: area.lines.map((line) => ({
          name: line.name,
          cells: line.cells.map((cell) => ({ name: cell.name, machines: [...cell.machines] })),
        })),
      })),
    })),
  };
}

export function uniqueChildName(existing: string[], base: string): string {
  if (!existing.includes(base)) return base;
  let n = 2;
  while (existing.includes(`${base}${n}`)) n += 1;
  return `${base}${n}`;
}

export function addChild(
  tree: GraphqlHierarchyTree,
  ref: NodeRef,
): { tree: GraphqlHierarchyTree; child: NodeRef } | null {
  const nextLevel = remainingChildren(ref.level)[0];
  if (!nextLevel) return null;
  const next = cloneTree(tree);
  const base = levelDef(nextLevel).defaultName ?? 'Child';
  switch (ref.level) {
    case 'enterprise': {
      const name = uniqueChildName(
        next.sites.map((s) => s.name),
        base,
      );
      next.sites.push({ name, areas: [] });
      return { tree: next, child: { level: 'site', site: next.sites.length - 1 } };
    }
    case 'site': {
      const areas = next.sites[ref.site].areas;
      const name = uniqueChildName(
        areas.map((a) => a.name),
        base,
      );
      areas.push({ name, kind: 'production', lines: [] });
      return { tree: next, child: { level: 'area', site: ref.site, area: areas.length - 1 } };
    }
    case 'area': {
      const lines = next.sites[ref.site].areas[ref.area].lines;
      const name = uniqueChildName(
        lines.map((l) => l.name),
        base,
      );
      lines.push({ name, cells: [] });
      return {
        tree: next,
        child: { level: 'line', site: ref.site, area: ref.area, line: lines.length - 1 },
      };
    }
    case 'line': {
      const cells = next.sites[ref.site].areas[ref.area].lines[ref.line].cells;
      const name = uniqueChildName(
        cells.map((c) => c.name),
        base,
      );
      cells.push({ name, machines: [] });
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
    case 'cell': {
      const machines =
        next.sites[ref.site].areas[ref.area].lines[ref.line].cells[ref.cell].machines;
      const name = uniqueChildName(machines, levelDef('machine').defaultName ?? 'Machine');
      machines.push(name);
      return {
        tree: next,
        child: {
          level: 'machine',
          site: ref.site,
          area: ref.area,
          line: ref.line,
          cell: ref.cell,
          machine: machines.length - 1,
        },
      };
    }
    case 'machine':
      return null;
  }
}

export function insertDescendant(
  tree: GraphqlHierarchyTree,
  parent: NodeRef,
  target: NodeLevel,
): { tree: GraphqlHierarchyTree; child: NodeRef } | null {
  let currentTree = tree;
  let currentRef = parent;
  while (currentRef.level !== target) {
    const result = addChild(currentTree, currentRef);
    if (!result) return null;
    currentTree = result.tree;
    currentRef = result.child;
  }
  return { tree: currentTree, child: currentRef };
}

export function nodeKey(ref: NodeRef): string {
  switch (ref.level) {
    case 'enterprise':
      return 'enterprise';
    case 'site':
      return `site:${ref.site}`;
    case 'area':
      return `area:${ref.site}:${ref.area}`;
    case 'line':
      return `line:${ref.site}:${ref.area}:${ref.line}`;
    case 'cell':
      return `cell:${ref.site}:${ref.area}:${ref.line}:${ref.cell}`;
    case 'machine':
      return `machine:${ref.site}:${ref.area}:${ref.line}:${ref.cell}:${ref.machine}`;
  }
}

export function childRefs(tree: GraphqlHierarchyTree, ref: NodeRef): NodeRef[] {
  switch (ref.level) {
    case 'enterprise':
      return tree.sites.map((_, site) => ({ level: 'site' as const, site }));
    case 'site':
      return tree.sites[ref.site].areas.map((_, area) => ({
        level: 'area' as const,
        site: ref.site,
        area,
      }));
    case 'area':
      return tree.sites[ref.site].areas[ref.area].lines.map((_, line) => ({
        level: 'line' as const,
        site: ref.site,
        area: ref.area,
        line,
      }));
    case 'line':
      return tree.sites[ref.site].areas[ref.area].lines[ref.line].cells.map((_, cell) => ({
        level: 'cell' as const,
        site: ref.site,
        area: ref.area,
        line: ref.line,
        cell,
      }));
    case 'cell':
      return tree.sites[ref.site].areas[ref.area].lines[ref.line].cells[ref.cell].machines.map(
        (_, machine) => ({
          level: 'machine' as const,
          site: ref.site,
          area: ref.area,
          line: ref.line,
          cell: ref.cell,
          machine,
        }),
      );
    case 'machine':
      return [];
  }
}

export function expandableKeys(tree: GraphqlHierarchyTree): string[] {
  const keys: string[] = [];
  const walk = (ref: NodeRef) => {
    const children = childRefs(tree, ref);
    if (children.length === 0) return;
    keys.push(nodeKey(ref));
    children.forEach(walk);
  };
  walk({ level: 'enterprise' });
  return keys;
}

export function ancestorKeys(ref: NodeRef): string[] {
  switch (ref.level) {
    case 'enterprise':
      return [];
    case 'site':
      return [nodeKey({ level: 'enterprise' })];
    case 'area':
      return [nodeKey({ level: 'site', site: ref.site }), nodeKey({ level: 'enterprise' })];
    case 'line':
      return [
        nodeKey({ level: 'area', site: ref.site, area: ref.area }),
        nodeKey({ level: 'site', site: ref.site }),
        nodeKey({ level: 'enterprise' }),
      ];
    case 'cell':
      return [
        nodeKey({ level: 'line', site: ref.site, area: ref.area, line: ref.line }),
        nodeKey({ level: 'area', site: ref.site, area: ref.area }),
        nodeKey({ level: 'site', site: ref.site }),
        nodeKey({ level: 'enterprise' }),
      ];
    case 'machine':
      return [
        nodeKey({
          level: 'cell',
          site: ref.site,
          area: ref.area,
          line: ref.line,
          cell: ref.cell,
        }),
        nodeKey({ level: 'line', site: ref.site, area: ref.area, line: ref.line }),
        nodeKey({ level: 'area', site: ref.site, area: ref.area }),
        nodeKey({ level: 'site', site: ref.site }),
        nodeKey({ level: 'enterprise' }),
      ];
  }
}

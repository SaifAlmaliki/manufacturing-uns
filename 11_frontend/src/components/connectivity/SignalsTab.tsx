import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Pencil, Plus, Trash2 } from 'lucide-react';
import { unsGraphQLClient } from '../../services/graphql/client';
import type {
  AccessAssetDto,
  GraphqlConnectivityServer,
  GraphqlConnectivityTagPatch,
  GraphqlOpcUaDataValue,
  GraphqlSignalDataType,
  GraphqlSignalSemanticClass,
  GraphqlSubscribedSignal,
  GraphqlUnitOfMeasure,
} from '../../services/graphql/types';
import { filterSubscribedSignals } from '../../lib/connectivity/signal-filters';
import {
  draftCount,
  mergeSignalDraft,
  stageSignalPatch,
  withAddedLabel,
  type SignalDrafts,
} from '../../lib/connectivity/signal-drafts';
import { formatOpcUaValue } from '../../lib/connectivity/map-servers';
import { assetLeafLabel } from '../../lib/condition-monitoring/match-tags';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  BtnGhost,
  BtnPrimary,
  ConsoleCard,
  ConsoleSelect,
  FilterToolbar,
  QualityLamp,
  type FilterToolbarSelect,
} from '../ui/console-ui';
import { SignalContextPanel } from './SignalContextPanel';

type LiveReading = { value: unknown; status: string };

const OTHER = '__other__';

const SEMANTIC_CLASSES: GraphqlSignalSemanticClass[] = [
  'MeasuredValue',
  'EnergyConsumption',
  'CounterOK',
  'CounterNOK',
  'State',
];

const DATA_TYPES: GraphqlSignalDataType[] = ['Double', 'Boolean', 'Integer', 'String'];

function rowKey(row: Pick<GraphqlSubscribedSignal, 'serverId' | 'nodeId'>): string {
  return `${row.serverId}\n${row.nodeId}`;
}

function parseRowKey(key: string): { serverId: string; nodeId: string } {
  const idx = key.indexOf('\n');
  return { serverId: key.slice(0, idx), nodeId: key.slice(idx + 1) };
}

function mergeUnit(
  catalog: GraphqlUnitOfMeasure[],
  saved: GraphqlUnitOfMeasure,
): GraphqlUnitOfMeasure[] {
  if (catalog.some((u) => u.symbol === saved.symbol)) return catalog;
  return [...catalog, saved];
}

function mergeLabel(catalog: string[], saved: string): string[] {
  if (catalog.includes(saved)) return catalog;
  return [...catalog, saved];
}

function unitsWithSelected(
  units: GraphqlUnitOfMeasure[],
  selected: string,
): GraphqlUnitOfMeasure[] {
  if (!selected || units.some((unit) => unit.symbol === selected)) return units;
  return [...units, { symbol: selected, name: selected }];
}

function assetsWithSelected(assets: AccessAssetDto[], selectedId: string): AccessAssetDto[] {
  if (!selectedId || assets.some((asset) => String(asset.id) === selectedId)) return assets;
  const id = Number(selectedId);
  return [
    ...assets,
    {
      id: Number.isFinite(id) ? id : 0,
      path: selectedId,
      segment: assetLeafLabel(selectedId),
      level: 'AREA',
    },
  ];
}

function withSelectedLiteral(catalog: string[], selected: string): string[] {
  if (!selected || catalog.includes(selected)) return catalog;
  return [...catalog, selected];
}

const EMPTY_COPY = 'Subscribe variables from Browse data on a server — then attach units here.';

export type SignalsToolbar = {
  search: { value: string; onChange: (value: string) => void; placeholder?: string };
  selects: FilterToolbarSelect[];
  trailing?: React.ReactNode;
};

type SignalsTabProps = {
  renderToolbar?: (toolbar: SignalsToolbar) => React.ReactNode;
  cloudEdgeMode?: boolean;
  expectedRevision?: number | null;
  selectedEdgeId?: string | null;
};

export const SignalsTab: React.FC<SignalsTabProps> = ({
  renderToolbar,
  cloudEdgeMode = false,
  expectedRevision = null,
  selectedEdgeId = null,
}) => {
  const [rows, setRows] = useState<GraphqlSubscribedSignal[]>([]);
  const [units, setUnits] = useState<GraphqlUnitOfMeasure[]>([]);
  const [labels, setLabels] = useState<string[]>([]);
  const [assets, setAssets] = useState<AccessAssetDto[]>([]);
  const [servers, setServers] = useState<GraphqlConnectivityServer[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [signalsLoadFailed, setSignalsLoadFailed] = useState(false);
  const [search, setSearch] = useState('');
  const [serverId, setServerId] = useState('');
  const [assetFilter, setAssetFilter] = useState('');
  const [missingUnit, setMissingUnit] = useState(false);
  const [semanticClass, setSemanticClass] = useState('');
  const [labelFilter, setLabelFilter] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [openSignal, setOpenSignal] = useState<GraphqlSubscribedSignal | null>(null);
  const [otherFor, setOtherFor] = useState<string | null>(null);
  const [otherKind, setOtherKind] = useState<'unit' | 'label'>('unit');
  const [otherSymbol, setOtherSymbol] = useState('');
  const [saveError, setSaveError] = useState<string | null>(null);
  const [liveByKey, setLiveByKey] = useState<Record<string, LiveReading>>({});
  const [drafts, setDrafts] = useState<SignalDrafts>({});
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [addSignalOpen, setAddSignalOpen] = useState(false);
  const [newAddress, setNewAddress] = useState('');
  const [newDisplayName, setNewDisplayName] = useState('');
  const [newTopic, setNewTopic] = useState('');
  const [newDataType, setNewDataType] = useState<GraphqlSignalDataType | ''>('');
  const [addSignalError, setAddSignalError] = useState<string | null>(null);
  const [addingSignal, setAddingSignal] = useState(false);
  const cloudWrite =
    cloudEdgeMode && expectedRevision != null ? { expectedRevision } : undefined;

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    setSignalsLoadFailed(false);
    try {
      const signals = await unsGraphQLClient.getSubscribedSignals();
      setRows(signals);
    } catch (err) {
      setSignalsLoadFailed(true);
      setLoadError(
        err instanceof Error
          ? `Connectivity catalog could not be loaded. ${err.message}`
          : 'Connectivity catalog could not be loaded. GraphQL returned an error — not an empty plant.',
      );
      setRows([]);
      setLoading(false);
      return;
    }

    const [unitResult, labelResult, assetResult, serverResult] = await Promise.allSettled([
      unsGraphQLClient.unitsOfMeasure(),
      unsGraphQLClient.signalLabels(),
      unsGraphQLClient.getAssets(),
      unsGraphQLClient.getConnectivityServers(),
    ]);

    const catalogErrors: string[] = [];
    if (unitResult.status === 'fulfilled') {
      setUnits(unitResult.value);
    } else {
      setUnits([]);
      catalogErrors.push(
        unitResult.reason instanceof Error
          ? unitResult.reason.message
          : 'units of measure could not be loaded',
      );
    }
    if (labelResult.status === 'fulfilled') {
      setLabels(labelResult.value);
    } else {
      setLabels([]);
      catalogErrors.push(
        labelResult.reason instanceof Error
          ? labelResult.reason.message
          : 'signal labels could not be loaded',
      );
    }
    if (assetResult.status === 'fulfilled') {
      setAssets(assetResult.value);
    } else {
      setAssets([]);
      catalogErrors.push(
        assetResult.reason instanceof Error
          ? assetResult.reason.message
          : 'assets could not be loaded',
      );
    }
    if (serverResult.status === 'fulfilled') {
      const scoped =
        cloudEdgeMode && selectedEdgeId
          ? serverResult.value.filter((server) => server.edgeId === selectedEdgeId)
          : serverResult.value;
      setServers(scoped);
    } else {
      setServers([]);
      catalogErrors.push(
        serverResult.reason instanceof Error
          ? serverResult.reason.message
          : 'servers could not be loaded',
      );
    }

    if (catalogErrors.length > 0) {
      setLoadError(`Connectivity catalog could not be loaded. ${catalogErrors.join('; ')}`);
    }

    setLoading(false);
  }, [cloudEdgeMode, selectedEdgeId]);

  useEffect(() => {
    void load();
  }, [load]);

  const liveTargetKey = rows.map((row) => rowKey(row)).join('|');
  const liveTargets = useMemo(
    () => (liveTargetKey ? liveTargetKey.split('|').map(parseRowKey) : []),
    [liveTargetKey],
  );

  useEffect(() => {
    if (liveTargets.length === 0) {
      setLiveByKey({});
      return;
    }
    let cancelled = false;
    const unsubs: Array<() => void> = [];

    void (async () => {
      let servers: GraphqlConnectivityServer[] = [];
      try {
        servers = await unsGraphQLClient.getConnectivityServers();
      } catch {
        return;
      }
      if (cancelled) return;

      const endpointById = new Map(servers.map((server) => [server.id, server.endpoint]));

      if (cloudEdgeMode) {
        const topics = [...new Set(rows.map((row) => row.mqttTopic).filter(Boolean))];
        if (topics.length > 0) {
          unsubs.push(
            unsGraphQLClient.subscribeMqttMessages(topics, (message) => {
              const match = rows.find((row) => row.mqttTopic === message.topic);
              if (!match) return;
              setLiveByKey((prev) => ({
                ...prev,
                [rowKey(match)]: {
                  value:
                    typeof message.payload === 'object' && message.payload && 'data' in message.payload
                      ? (message.payload as { data?: unknown }).data
                      : message.payload,
                  status: 'Good',
                },
              }));
            }),
          );
        }
      } else {
        const groups = new Map<string, { serverId: string; endpoint: string; nodeIds: string[] }>();
        for (const target of liveTargets) {
          const endpoint = endpointById.get(target.serverId);
          if (!endpoint) continue;
          const group = groups.get(target.serverId) ?? {
            serverId: target.serverId,
            endpoint,
            nodeIds: [],
          };
          group.nodeIds.push(target.nodeId);
          groups.set(target.serverId, group);
        }

        const applyReading = (serverId: string, reading: GraphqlOpcUaDataValue) => {
          setLiveByKey((prev) => ({
            ...prev,
            [rowKey({ serverId, nodeId: reading.nodeId })]: {
              value: reading.value,
              status: reading.status,
            },
          }));
        };

        for (const group of groups.values()) {
          try {
            const values = await unsGraphQLClient.readOpcUaNodes(group.endpoint, group.nodeIds);
            if (cancelled) return;
            for (const reading of values) applyReading(group.serverId, reading);
          } catch {
            // Live reads are optional — the catalog row still stands.
          }
          unsubs.push(
            unsGraphQLClient.subscribeOpcUaDataChanges(group.endpoint, group.nodeIds, (reading) => {
              applyReading(group.serverId, reading);
            }),
          );
        }
      }
    })();

    return () => {
      cancelled = true;
      for (const unsub of unsubs) unsub();
    };
  }, [cloudEdgeMode, liveTargets, rows, servers]);

  const displayedRows = useMemo(
    () => rows.map((row) => mergeSignalDraft(row, drafts[rowKey(row)])),
    [rows, drafts],
  );

  const filtered = useMemo(() => {
    const byCatalog = filterSubscribedSignals(displayedRows, {
      search,
      serverId: serverId || undefined,
      missingUnit: missingUnit || undefined,
      semanticClass: (semanticClass || undefined) as GraphqlSignalSemanticClass | undefined,
      label: labelFilter || undefined,
    });
    if (!assetFilter) return byCatalog;
    return byCatalog.filter((row) => String(row.assetId ?? '') === assetFilter);
  }, [displayedRows, search, serverId, assetFilter, missingUnit, semanticClass, labelFilter]);

  const serverOptions = useMemo(() => {
    const seen = new Map<string, string>();
    for (const row of rows) {
      if (!seen.has(row.serverId)) seen.set(row.serverId, row.serverName);
    }
    // Include the full catalog too — a fresh S7/EtherNet-IP server has no signals
    // yet, but still needs to be selectable so Add signal can author its first tag.
    for (const server of servers) {
      if (!seen.has(server.id)) seen.set(server.id, server.name);
    }
    return [...seen.entries()].map(([value, label]) => ({ value, label }));
  }, [rows, servers]);

  const selectedServer = useMemo(
    () => servers.find((server) => server.id === serverId) ?? null,
    [servers, serverId],
  );
  const showAddSignal = Boolean(
    selectedServer &&
      (selectedServer.protocol === 'S7' ||
        selectedServer.protocol === 'ETHERNET_IP' ||
        selectedServer.protocol === 'MODBUS'),
  );

  const applyPatch = async (
    serverIdValue: string,
    nodeId: string,
    patch: GraphqlConnectivityTagPatch,
  ): Promise<boolean> => {
    try {
      const updated = await unsGraphQLClient.updateConnectivityTag(
        serverIdValue,
        nodeId,
        patch,
        cloudWrite,
      );
      setRows((prev) =>
        prev.map((row) =>
          row.serverId === serverIdValue && row.nodeId === nodeId
            ? { ...row, ...updated, serverName: row.serverName }
            : row,
        ),
      );
      setSaveError(null);
      return true;
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Signal was not saved');
      return false;
    }
  };

  const stageOn = (keys: string[], patch: GraphqlConnectivityTagPatch) => {
    setDrafts((prev) => {
      let next = prev;
      for (const key of keys) {
        const row = rows.find((item) => rowKey(item) === key);
        if (!row) continue;
        next = stageSignalPatch(next, key, row, patch);
      }
      return next;
    });
    setSaveError(null);
  };

  const persistDrafts = async () => {
    const entries = Object.entries(drafts);
    if (entries.length === 0) return;
    setSaving(true);
    setSaveError(null);
    try {
      for (const [key, patch] of entries) {
        const target = parseRowKey(key);
        const ok = await applyPatch(target.serverId, target.nodeId, patch);
        if (!ok) return;
        setDrafts((prev) => {
          const next = { ...prev };
          delete next[key];
          return next;
        });
      }
    } finally {
      setSaving(false);
    }
  };

  const persistOtherUnit = async (target: { serverId: string; nodeId: string } | 'bulk') => {
    const symbol = otherSymbol.trim();
    if (!symbol) return;
    try {
      const saved = await unsGraphQLClient.saveUnitOfMeasure(symbol, undefined);
      let catalog: GraphqlUnitOfMeasure[] = [];
      try {
        catalog = await unsGraphQLClient.unitsOfMeasure();
      } catch {
        catalog = units;
      }
      setUnits(mergeUnit(catalog, saved));
      const keys = target === 'bulk' ? [...selected] : [rowKey(target)];
      stageOn(keys, { unitOfMeasure: saved.symbol });
      setOtherFor(null);
      setOtherSymbol('');
      setSaveError(null);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Unit of Measure was not saved');
    }
  };

  const stageLabelName = (name: string, target: { serverId: string; nodeId: string } | 'bulk') => {
    const targets = target === 'bulk' ? [...selected].map(parseRowKey) : [target];
    setDrafts((prev) => {
      let next = prev;
      for (const item of targets) {
        const key = rowKey(item);
        const row = rows.find((r) => r.serverId === item.serverId && r.nodeId === item.nodeId);
        if (!row) continue;
        next = stageSignalPatch(next, key, row, withAddedLabel(row, prev[key], name));
      }
      return next;
    });
    setSaveError(null);
  };

  const persistOtherLabel = async (target: { serverId: string; nodeId: string } | 'bulk') => {
    const name = otherSymbol.trim();
    if (!name) return;
    try {
      const saved = await unsGraphQLClient.saveSignalLabel(name);
      let catalog: string[] = [];
      try {
        catalog = await unsGraphQLClient.signalLabels();
      } catch {
        catalog = labels;
      }
      setLabels(mergeLabel(catalog, saved));
      stageLabelName(saved, target);
      setOtherFor(null);
      setOtherSymbol('');
      setSaveError(null);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Signal label was not saved');
    }
  };

  const resetAddSignalDraft = () => {
    setNewAddress('');
    setNewDisplayName('');
    setNewTopic('');
    setNewDataType('');
    setAddSignalError(null);
  };

  /** S7/EtherNet-IP have no browse discovery, so the engineer authors the tag's address directly. */
  const handleAddSignal = async () => {
    if (!selectedServer) return;
    const nodeId = newAddress.trim();
    const mqttTopic = newTopic.trim();
    if (!nodeId || !mqttTopic) {
      setAddSignalError('Address and MQTT topic are required.');
      return;
    }
    setAddingSignal(true);
    setAddSignalError(null);
    try {
      const displayName = newDisplayName.trim() || nodeId;
      const saved = await unsGraphQLClient.saveConnectivityTag(
        selectedServer.id,
        {
          nodeId,
          browsePath: '',
          displayName,
          mqttTopic,
          subscribed: true,
          dataType: newDataType || null,
        },
        cloudWrite,
      );
      const tag: GraphqlSubscribedSignal = {
        serverId: selectedServer.id,
        serverName: selectedServer.name,
        nodeId: saved.nodeId,
        browsePath: '',
        displayName,
        mqttTopic: saved.mqttTopic,
        subscribed: saved.subscribed,
        dataType: saved.dataType ?? null,
        labels: [],
      };
      setRows((prev) => [...prev, tag]);
      setAddSignalOpen(false);
      resetAddSignalDraft();
    } catch (err) {
      setAddSignalError(err instanceof Error ? err.message : 'Signal was not saved');
    } finally {
      setAddingSignal(false);
    }
  };

  const deleteSelected = async () => {
    const targets = [...selected].map(parseRowKey);
    if (targets.length === 0) return;
    setDeleting(true);
    setSaveError(null);
    try {
      for (const target of targets) {
        await unsGraphQLClient.unsubscribeConnectivityTag(
          target.serverId,
          target.nodeId,
          cloudWrite,
        );
        const key = rowKey(target);
        setRows((prev) =>
          prev.filter((row) => !(row.serverId === target.serverId && row.nodeId === target.nodeId)),
        );
        setDrafts((prev) => {
          if (!(key in prev)) return prev;
          const next = { ...prev };
          delete next[key];
          return next;
        });
        setSelected((prev) => {
          const next = new Set(prev);
          next.delete(key);
          return next;
        });
      }
      setConfirmDelete(false);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Selected signals were not deleted');
      setConfirmDelete(false);
    } finally {
      setDeleting(false);
    }
  };

  const openOther = (kind: 'unit' | 'label', key: string) => {
    setOtherKind(kind);
    setOtherFor(key);
    setOtherSymbol('');
  };

  const toggleSelected = (key: string, on: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (on) next.add(key);
      else next.delete(key);
      return next;
    });
  };

  const allFilteredSelected =
    filtered.length > 0 && filtered.every((row) => selected.has(rowKey(row)));

  const unitSelect = (
    ariaLabel: string,
    value: string,
    onChoose: (symbol: string | null) => void,
    otherKey: string,
  ) => (
    <div className="flex min-w-[7.5rem] items-center gap-1">
      <ConsoleSelect
        aria-label={ariaLabel}
        className="min-w-[6.5rem]"
        value={otherFor === otherKey && otherKind === 'unit' ? OTHER : value}
        onChange={(e) => {
          const next = e.target.value;
          if (next === OTHER) {
            openOther('unit', otherKey);
            return;
          }
          if (otherFor === otherKey && otherKind === 'unit') setOtherFor(null);
          onChoose(next === '' ? null : next);
        }}
      >
        <option value="">—</option>
        {unitsWithSelected(units, value).map((unit) => (
          <option key={unit.symbol} value={unit.symbol}>
            {unit.symbol}
          </option>
        ))}
        <option value={OTHER}>Other…</option>
      </ConsoleSelect>
    </div>
  );

  const dirtyCount = draftCount(drafts);
  const toolbar: SignalsToolbar = {
    search: { value: search, onChange: setSearch, placeholder: 'Search name, topic, node…' },
    selects: [
      {
        value: serverId,
        onChange: setServerId,
        'aria-label': 'Server',
        options: [{ value: '', label: 'All servers' }, ...serverOptions],
      },
      {
        value: assetFilter,
        onChange: setAssetFilter,
        'aria-label': 'Asset filter',
        options: [
          { value: '', label: 'All Assets' },
          ...assets.map((asset) => ({
            value: String(asset.id),
            label: assetLeafLabel(asset.path, asset.segment),
          })),
        ],
      },
      {
        value: missingUnit ? 'missing' : '',
        onChange: (v) => setMissingUnit(v === 'missing'),
        'aria-label': 'Missing Unit of Measure',
        options: [
          { value: '', label: 'All signals' },
          { value: 'missing', label: 'Missing Unit of Measure' },
        ],
      },
      {
        value: semanticClass,
        onChange: setSemanticClass,
        'aria-label': 'Semantic class',
        options: [
          { value: '', label: 'All classes' },
          ...SEMANTIC_CLASSES.map((cls) => ({ value: cls, label: cls })),
        ],
      },
      {
        value: labelFilter,
        onChange: setLabelFilter,
        'aria-label': 'Label',
        options: [
          { value: '', label: 'All labels' },
          ...labels.map((name) => ({ value: name, label: name })),
        ],
      },
    ],
    trailing: (
      <div className="ml-auto flex shrink-0 items-center gap-1">
        {showAddSignal && (
          <BtnGhost
            className="px-2 py-1 text-[11px]"
            aria-label="Add signal"
            onClick={() => {
              resetAddSignalDraft();
              setAddSignalOpen(true);
            }}
          >
            <Plus className="size-3.5" />
            Add signal
          </BtnGhost>
        )}
        {dirtyCount > 0 ? (
          <BtnGhost
            className="px-2 py-1 text-[11px]"
            onClick={() => {
              setDrafts({});
              setSaveError(null);
            }}
          >
            Discard
          </BtnGhost>
        ) : null}
        <BtnPrimary
          className="px-2.5 py-1 text-[11px]"
          disabled={dirtyCount === 0 || saving}
          aria-label="Save signal changes"
          onClick={() => void persistDrafts()}
        >
          {saving
            ? 'Saving…'
            : dirtyCount > 0
              ? `Save ${dirtyCount} ${dirtyCount === 1 ? 'change' : 'changes'}`
              : 'Save'}
        </BtnPrimary>
      </div>
    ),
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      {renderToolbar ? (
        renderToolbar(toolbar)
      ) : (
        <FilterToolbar search={toolbar.search} selects={toolbar.selects} trailing={toolbar.trailing} />
      )}

      {otherFor && (
        <div className="flex flex-wrap items-center gap-1.5 rounded-md border border-border bg-muted/40 px-2 py-1.5">
          <span className="text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
            {otherKind === 'label' ? 'New signal label' : 'New Unit of Measure'}
          </span>
          <input
            aria-label={otherKind === 'label' ? 'New signal label' : 'New Unit of Measure'}
            value={otherSymbol}
            onChange={(e) => setOtherSymbol(e.target.value)}
            className="h-7 w-28 rounded-md border border-border bg-background px-2 font-mono text-xs text-foreground focus:border-[#FF7A00]/50 focus:outline-none focus:ring-1 focus:ring-[#FF7A00]/30"
            placeholder={otherKind === 'label' ? 'Cycle' : 'NTU'}
          />
          <BtnGhost
            className="px-2 py-1 text-[11px]"
            onClick={() => {
              const target = otherFor === 'bulk' ? 'bulk' : parseRowKey(otherFor);
              if (otherKind === 'label') void persistOtherLabel(target);
              else void persistOtherUnit(target);
            }}
          >
            Confirm
          </BtnGhost>
        </div>
      )}

      {saveError && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
          {saveError}
        </div>
      )}

      {loadError && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
          {loadError}
        </div>
      )}

      {loading ? (
        <ConsoleCard padding="md" className="text-sm text-muted-foreground">
          Loading subscribed signals…
        </ConsoleCard>
      ) : signalsLoadFailed ? null : filtered.length === 0 ? (
        <ConsoleCard padding="md" className="text-sm text-muted-foreground">
          {rows.length === 0 ? EMPTY_COPY : 'No signals match this search.'}
        </ConsoleCard>
      ) : (
        <ConsoleCard padding="none" className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[980px] border-collapse text-left text-sm">
              <thead className="border-b border-border bg-muted/50 text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
                <tr>
                  <th className="w-8 px-2 py-1.5">
                    <input
                      type="checkbox"
                      aria-label="Select all"
                      checked={allFilteredSelected}
                      onChange={(e) => {
                        const on = e.target.checked;
                        setSelected((prev) => {
                          const next = new Set(prev);
                          for (const row of filtered) {
                            const key = rowKey(row);
                            if (on) next.add(key);
                            else next.delete(key);
                          }
                          return next;
                        });
                      }}
                    />
                  </th>
                  <th className="px-2 py-1.5">Signal</th>
                  <th className="px-2 py-1.5">Value</th>
                  <th className="px-2 py-1.5">Health</th>
                  <th className="px-2 py-1.5">Server</th>
                  <th className="px-2 py-1.5">Asset</th>
                  <th className="px-2 py-1.5">Unit of Measure</th>
                  <th className="px-2 py-1.5">Class</th>
                  <th className="px-2 py-1.5">Data type</th>
                  <th className="px-2 py-1.5">Labels</th>
                </tr>
                {selected.size > 0 && (
                  <tr className="border-t border-[#FF7A00]/20 bg-[#FF7A00]/8 text-[11px] font-normal normal-case tracking-normal text-foreground">
                    <td className="whitespace-nowrap px-2 py-1">
                      <span
                        className="text-[10px] font-medium uppercase tracking-[0.16em] text-[#FF7A00] tabular-nums"
                        aria-label={`${selected.size} selected`}
                      >
                        {selected.size}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-2 py-1">
                      <div className="flex items-center gap-1">
                        <BtnGhost
                          className="px-2 py-1 text-[11px] text-rose-400 hover:text-rose-300"
                          aria-label="Delete selected"
                          onClick={() => setConfirmDelete(true)}
                        >
                          <Trash2 className="size-3" />
                          Delete
                        </BtnGhost>
                        <BtnGhost
                          className="px-2 py-1 text-[11px]"
                          onClick={() => setSelected(new Set())}
                        >
                          Clear
                        </BtnGhost>
                      </div>
                    </td>
                    <td className="px-2 py-1" />
                    <td className="px-2 py-1" />
                    <td className="px-2 py-1" />
                    <td className="px-2 py-1">
                      <ConsoleSelect
                        aria-label="Apply Asset"
                        className="w-[7.5rem] max-w-[7.5rem]"
                        value=""
                        onChange={(e) => {
                          const raw = e.target.value;
                          if (!raw) return;
                          stageOn([...selected], { assetId: raw === '__clear__' ? null : Number(raw) });
                        }}
                      >
                        <option value="">Asset…</option>
                        <option value="__clear__">Clear Asset</option>
                        {assets.map((asset) => (
                          <option key={asset.id} value={String(asset.id)} title={asset.path}>
                            {assetLeafLabel(asset.path, asset.segment)}
                          </option>
                        ))}
                      </ConsoleSelect>
                    </td>
                    <td className="px-2 py-1">
                      {unitSelect(
                        'Apply Unit of Measure',
                        '',
                        (symbol) => stageOn([...selected], { unitOfMeasure: symbol }),
                        'bulk',
                      )}
                    </td>
                    <td className="px-2 py-1">
                      <ConsoleSelect
                        aria-label="Apply class"
                        className="min-w-[8rem]"
                        value=""
                        onChange={(e) => {
                          const raw = e.target.value;
                          stageOn([...selected], {
                            semanticClass: raw === '' ? null : (raw as GraphqlSignalSemanticClass),
                          });
                        }}
                      >
                        <option value="">Class…</option>
                        {SEMANTIC_CLASSES.map((cls) => (
                          <option key={cls} value={cls}>
                            {cls}
                          </option>
                        ))}
                      </ConsoleSelect>
                    </td>
                    <td className="px-2 py-1">
                      <ConsoleSelect
                        aria-label="Apply data type"
                        className="min-w-[6rem]"
                        value=""
                        onChange={(e) => {
                          const raw = e.target.value;
                          stageOn([...selected], {
                            dataType: raw === '' ? null : (raw as GraphqlSignalDataType),
                          });
                        }}
                      >
                        <option value="">Data type…</option>
                        {DATA_TYPES.map((type) => (
                          <option key={type} value={type}>
                            {type}
                          </option>
                        ))}
                      </ConsoleSelect>
                    </td>
                    <td className="px-2 py-1">
                      <ConsoleSelect
                        aria-label="Apply label"
                        className="w-[7.5rem]"
                        value={otherFor === 'bulk' && otherKind === 'label' ? OTHER : ''}
                        onChange={(e) => {
                          const name = e.target.value;
                          if (!name) return;
                          if (name === OTHER) {
                            openOther('label', 'bulk');
                            return;
                          }
                          if (otherFor === 'bulk' && otherKind === 'label') setOtherFor(null);
                          stageLabelName(name, 'bulk');
                        }}
                      >
                        <option value="">Label…</option>
                        {labels.map((name) => (
                          <option key={name} value={name}>
                            {name}
                          </option>
                        ))}
                        <option value={OTHER}>Other…</option>
                      </ConsoleSelect>
                    </td>
                  </tr>
                )}
              </thead>
              <tbody className="divide-y divide-border text-xs">
                {filtered.map((row) => {
                  const key = rowKey(row);
                  const live = liveByKey[key];
                  const assetId = row.assetId != null ? String(row.assetId) : '';
                  const catalogRow = rows.find((item) => rowKey(item) === key) ?? row;
                  const dirty = Boolean(drafts[key]);
                  return (
                    <tr key={key} className={dirty ? 'bg-[#FF7A00]/5 hover:bg-[#FF7A00]/10' : 'hover:bg-muted/60'}>
                      <td className="px-2 py-1">
                        <input
                          type="checkbox"
                          aria-label={`Select ${row.displayName}`}
                          checked={selected.has(key)}
                          onChange={(e) => toggleSelected(key, e.target.checked)}
                        />
                      </td>
                      <td className="px-2 py-1">
                        <div className="flex w-[10.5rem] max-w-[10.5rem] flex-col gap-0.5">
                          <div className="flex items-center gap-1">
                            <button
                              type="button"
                              onClick={() => setOpenSignal(catalogRow)}
                              className="min-w-0 truncate font-heading text-left text-[13px] font-semibold text-foreground hover:text-[#FF7A00]"
                            >
                              {row.displayName}
                            </button>
                            <button
                              type="button"
                              aria-label={`Edit ${row.displayName}`}
                              title="Edit name and topic"
                              onClick={() => setOpenSignal(catalogRow)}
                              className="inline-flex size-5 shrink-0 items-center justify-center rounded-sm text-muted-foreground hover:bg-[#FF7A00]/15 hover:text-[#FF7A00]"
                            >
                              <Pencil className="size-3" />
                            </button>
                          </div>
                          <span
                            className="topic-cable whitespace-normal break-all text-[10px] leading-snug"
                            title={row.mqttTopic}
                          >
                            {row.mqttTopic || '—'}
                          </span>
                        </div>
                      </td>
                      <td className="whitespace-nowrap px-2 py-1 font-mono text-[12px] font-semibold tabular-nums text-[#FF7A00]">
                        {formatOpcUaValue(live?.value)}
                      </td>
                      <td className="px-2 py-1">
                        {live?.status ? <QualityLamp status={live.status} /> : '—'}
                      </td>
                      <td className="px-2 py-1 text-muted-foreground">{row.serverName}</td>
                      <td className="px-2 py-1">
                        <ConsoleSelect
                          aria-label={`Asset for ${row.displayName}`}
                          className="w-[7.5rem] max-w-[7.5rem]"
                          title={
                            assetsWithSelected(assets, assetId).find(
                              (asset) => String(asset.id) === assetId,
                            )?.path
                          }
                          value={assetId}
                          onChange={(e) => {
                            const raw = e.target.value;
                            stageOn([key], { assetId: raw === '' ? null : Number(raw) });
                          }}
                        >
                          <option value="">—</option>
                          {assetsWithSelected(assets, assetId).map((asset) => (
                            <option key={asset.id} value={String(asset.id)} title={asset.path}>
                              {assetLeafLabel(asset.path, asset.segment)}
                            </option>
                          ))}
                        </ConsoleSelect>
                      </td>
                      <td className="px-2 py-1">
                        {unitSelect(
                          `Unit of Measure for ${row.displayName}`,
                          row.unitOfMeasure ?? '',
                          (symbol) => stageOn([key], { unitOfMeasure: symbol }),
                          key,
                        )}
                      </td>
                      <td className="px-2 py-1">
                        <ConsoleSelect
                          aria-label={`Class for ${row.displayName}`}
                          className="min-w-[8rem]"
                          value={row.semanticClass ?? ''}
                          onChange={(e) => {
                            const raw = e.target.value;
                            stageOn([key], {
                              semanticClass:
                                raw === '' ? null : (raw as GraphqlSignalSemanticClass),
                            });
                          }}
                        >
                          <option value="">—</option>
                          {withSelectedLiteral(SEMANTIC_CLASSES, row.semanticClass ?? '').map(
                            (cls) => (
                              <option key={cls} value={cls}>
                                {cls}
                              </option>
                            ),
                          )}
                        </ConsoleSelect>
                      </td>
                      <td className="px-2 py-1">
                        <ConsoleSelect
                          aria-label={`Data type for ${row.displayName}`}
                          className="min-w-[6rem]"
                          value={row.dataType ?? ''}
                          onChange={(e) => {
                            const raw = e.target.value;
                            stageOn([key], {
                              dataType: raw === '' ? null : (raw as GraphqlSignalDataType),
                            });
                          }}
                        >
                          <option value="">—</option>
                          {withSelectedLiteral(DATA_TYPES, row.dataType ?? '').map((type) => (
                            <option key={type} value={type}>
                              {type}
                            </option>
                          ))}
                        </ConsoleSelect>
                      </td>
                      <td className="px-2 py-1">
                        <div className="flex flex-wrap items-center gap-1">
                          {(row.labels ?? []).map((name) => (
                            <span
                              key={name}
                              className="rounded-md bg-muted px-1.5 py-0.5 font-mono text-[10px] text-foreground"
                            >
                              {name}
                            </span>
                          ))}
                          <ConsoleSelect
                            aria-label={`Add label to ${row.displayName}`}
                            className="w-[7.5rem]"
                            value={otherFor === key && otherKind === 'label' ? OTHER : ''}
                            onChange={(e) => {
                              const name = e.target.value;
                              if (!name) return;
                              if (name === OTHER) {
                                openOther('label', key);
                                return;
                              }
                              if (otherFor === key && otherKind === 'label') setOtherFor(null);
                              stageLabelName(name, { serverId: row.serverId, nodeId: row.nodeId });
                            }}
                          >
                            <option value="">Add…</option>
                            {labels
                              .filter((name) => !(row.labels ?? []).includes(name))
                              .map((name) => (
                                <option key={name} value={name}>
                                  {name}
                                </option>
                              ))}
                            <option value={OTHER}>Other…</option>
                          </ConsoleSelect>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </ConsoleCard>
      )}

      {openSignal && (
        <SignalContextPanel
          signal={openSignal}
          cloudWrite={cloudWrite}
          onClose={() => setOpenSignal(null)}
          onUpdated={(next) => {
            setRows((prev) =>
              prev.map((row) =>
                row.serverId === next.serverId && row.nodeId === next.nodeId ? next : row,
              ),
            );
            setOpenSignal(next);
          }}
          onUnsubscribed={(serverIdValue, nodeId) => {
            const key = rowKey({ serverId: serverIdValue, nodeId });
            setRows((prev) =>
              prev.filter((row) => !(row.serverId === serverIdValue && row.nodeId === nodeId)),
            );
            setSelected((prev) => {
              const next = new Set(prev);
              next.delete(key);
              return next;
            });
            setDrafts((prev) => {
              if (!(key in prev)) return prev;
              const next = { ...prev };
              delete next[key];
              return next;
            });
            setOpenSignal(null);
          }}
        />
      )}

      <Dialog open={confirmDelete} onOpenChange={(open) => !open && setConfirmDelete(false)}>
        <DialogContent
          aria-label="Confirm delete"
          showCloseButton={false}
          className="instrument-panel instrument-grain border-[#FF7A00]/20 sm:max-w-sm"
        >
          <DialogHeader>
            <DialogTitle className="font-heading text-lg">
              Delete {selected.size} selected {selected.size === 1 ? 'signal' : 'signals'}?
            </DialogTitle>
            <DialogDescription>
              Selected signals are unsubscribed and removed from the catalog. Condition Monitoring
              stops showing them after the next refresh.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmDelete(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => void deleteSelected()}
              disabled={deleting}
              aria-label="Confirm"
            >
              {deleting ? 'Deleting…' : 'Confirm'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={addSignalOpen}
        onOpenChange={(open) => {
          setAddSignalOpen(open);
          if (!open) resetAddSignalDraft();
        }}
      >
        <DialogContent
          aria-label="Add signal"
          showCloseButton={false}
          className="instrument-panel instrument-grain border-[#FF7A00]/20 sm:max-w-md"
        >
          <DialogHeader>
            <DialogTitle className="font-heading text-lg">Add signal</DialogTitle>
            <DialogDescription>
              {selectedServer?.name ?? 'This server'} has no browse discovery — author the
              tag&apos;s address directly.
            </DialogDescription>
          </DialogHeader>
          {addSignalError && (
            <div className="rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              {addSignalError}
            </div>
          )}
          <div className="grid gap-3">
            <div className="grid gap-1.5">
              <Label htmlFor="signal-address">Address</Label>
              <Input
                id="signal-address"
                aria-label="Address"
                value={newAddress}
                onChange={(e) => setNewAddress(e.target.value)}
                placeholder="%ID103"
                className="font-mono text-xs"
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="signal-display-name">Display name</Label>
              <Input
                id="signal-display-name"
                aria-label="Display name"
                value={newDisplayName}
                onChange={(e) => setNewDisplayName(e.target.value)}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="signal-topic">MQTT topic</Label>
              <Input
                id="signal-topic"
                aria-label="MQTT topic"
                value={newTopic}
                onChange={(e) => setNewTopic(e.target.value)}
                placeholder="Acme/Line/Speed"
                className="font-mono text-xs"
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="signal-data-type">Data type</Label>
              <ConsoleSelect
                id="signal-data-type"
                aria-label="Data type"
                value={newDataType}
                onChange={(e) => setNewDataType(e.target.value as GraphqlSignalDataType | '')}
              >
                <option value="">—</option>
                {DATA_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </ConsoleSelect>
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setAddSignalOpen(false);
                resetAddSignalDraft();
              }}
            >
              Cancel
            </Button>
            <Button onClick={() => void handleAddSignal()} disabled={addingSignal} aria-label="Add">
              {addingSignal ? 'Adding…' : 'Add'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

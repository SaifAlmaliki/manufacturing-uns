import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { unsGraphQLClient } from '../../services/graphql/client';
import type {
  AccessAssetDto,
  GraphqlConnectivityTagPatch,
  GraphqlSignalDataType,
  GraphqlSignalSemanticClass,
  GraphqlSubscribedSignal,
  GraphqlUnitOfMeasure,
} from '../../services/graphql/types';
import { filterSubscribedSignals } from '../../lib/connectivity/signal-filters';
import {
  BtnGhost,
  ConsoleCard,
  ConsoleSelect,
  FilterToolbar,
} from '../ui/console-ui';
import { SignalContextPanel } from './SignalContextPanel';

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

const EMPTY_COPY = 'Subscribe variables from Browse data on a server — then attach units here.';

export const SignalsTab: React.FC = () => {
  const [rows, setRows] = useState<GraphqlSubscribedSignal[]>([]);
  const [units, setUnits] = useState<GraphqlUnitOfMeasure[]>([]);
  const [labels, setLabels] = useState<string[]>([]);
  const [assets, setAssets] = useState<AccessAssetDto[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [serverId, setServerId] = useState('');
  const [assetFilter, setAssetFilter] = useState('');
  const [missingUnit, setMissingUnit] = useState(false);
  const [semanticClass, setSemanticClass] = useState('');
  const [labelFilter, setLabelFilter] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [openSignal, setOpenSignal] = useState<GraphqlSubscribedSignal | null>(null);
  const [otherFor, setOtherFor] = useState<string | null>(null);
  const [otherSymbol, setOtherSymbol] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [signals, unitRows, labelRows, assetRows] = await Promise.all([
        unsGraphQLClient.getSubscribedSignals(),
        unsGraphQLClient.unitsOfMeasure().catch(() => [] as GraphqlUnitOfMeasure[]),
        unsGraphQLClient.signalLabels().catch(() => [] as string[]),
        unsGraphQLClient.getAssets().catch(() => [] as AccessAssetDto[]),
      ]);
      setRows(signals);
      setUnits(unitRows);
      setLabels(labelRows);
      setAssets(assetRows);
    } catch (err) {
      setLoadError(
        err instanceof Error
          ? `Connectivity catalog could not be loaded. ${err.message}`
          : 'Connectivity catalog could not be loaded. GraphQL returned an error — not an empty plant.',
      );
      setRows([]);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const filtered = useMemo(() => {
    const byCatalog = filterSubscribedSignals(rows, {
      search,
      serverId: serverId || undefined,
      missingUnit: missingUnit || undefined,
      semanticClass: (semanticClass || undefined) as GraphqlSignalSemanticClass | undefined,
      label: labelFilter || undefined,
    });
    if (!assetFilter) return byCatalog;
    return byCatalog.filter((row) => String(row.assetId ?? '') === assetFilter);
  }, [rows, search, serverId, assetFilter, missingUnit, semanticClass, labelFilter]);

  const serverOptions = useMemo(() => {
    const seen = new Map<string, string>();
    for (const row of rows) {
      if (!seen.has(row.serverId)) seen.set(row.serverId, row.serverName);
    }
    return [...seen.entries()].map(([value, label]) => ({ value, label }));
  }, [rows]);

  const applyPatch = async (
    serverIdValue: string,
    nodeId: string,
    patch: GraphqlConnectivityTagPatch,
  ) => {
    const updated = await unsGraphQLClient.updateConnectivityTag(serverIdValue, nodeId, patch);
    setRows((prev) =>
      prev.map((row) =>
        row.serverId === serverIdValue && row.nodeId === nodeId
          ? { ...row, ...updated, serverName: row.serverName }
          : row,
      ),
    );
  };

  const persistOtherUnit = async (target: { serverId: string; nodeId: string } | 'bulk') => {
    const symbol = otherSymbol.trim();
    if (!symbol) return;
    const saved = await unsGraphQLClient.saveUnitOfMeasure(symbol, undefined);
    let catalog: GraphqlUnitOfMeasure[] = [];
    try {
      catalog = await unsGraphQLClient.unitsOfMeasure();
    } catch {
      catalog = units;
    }
    setUnits(mergeUnit(catalog, saved));
    setOtherFor(null);
    setOtherSymbol('');
    if (target === 'bulk') {
      await applyBulk({ unitOfMeasure: saved.symbol });
    } else {
      await applyPatch(target.serverId, target.nodeId, { unitOfMeasure: saved.symbol });
    }
  };

  const applyBulk = async (patch: GraphqlConnectivityTagPatch) => {
    const targets = [...selected].map(parseRowKey);
    for (const target of targets) {
      await applyPatch(target.serverId, target.nodeId, patch);
    }
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
        className="h-7 px-1.5 py-0.5 text-[11px]"
        value={otherFor === otherKey ? OTHER : value}
        onChange={(e) => {
          const next = e.target.value;
          if (next === OTHER) {
            setOtherFor(otherKey);
            setOtherSymbol('');
            return;
          }
          if (otherFor === otherKey) setOtherFor(null);
          onChoose(next === '' ? null : next);
        }}
      >
        <option value="">—</option>
        {units.map((unit) => (
          <option key={unit.symbol} value={unit.symbol}>
            {unit.symbol}
          </option>
        ))}
        <option value={OTHER}>Other…</option>
      </ConsoleSelect>
    </div>
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <FilterToolbar
        search={{ value: search, onChange: setSearch, placeholder: 'Search name, topic, node…' }}
        selects={[
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
              ...assets.map((asset) => ({ value: String(asset.id), label: asset.path })),
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
        ]}
      />

      {selected.size > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 rounded-md border border-[#FF7A00]/25 bg-[#FF7A00]/8 px-2 py-1.5">
          <span className="text-[10px] font-medium uppercase tracking-[0.16em] text-[#FF7A00]">
            {selected.size} selected
          </span>
          {unitSelect(
            'Apply Unit of Measure',
            '',
            (symbol) => void applyBulk({ unitOfMeasure: symbol }),
            'bulk',
          )}
          <ConsoleSelect
            aria-label="Apply Asset"
            className="h-7 max-w-[14rem] px-1.5 py-0.5 text-[11px]"
            value=""
            onChange={(e) => {
              const raw = e.target.value;
              if (!raw) return;
              void applyBulk({ assetId: raw === '__clear__' ? null : Number(raw) });
            }}
          >
            <option value="">Asset…</option>
            <option value="__clear__">Clear Asset</option>
            {assets.map((asset) => (
              <option key={asset.id} value={String(asset.id)}>
                {asset.path}
              </option>
            ))}
          </ConsoleSelect>
          <ConsoleSelect
            aria-label="Apply class"
            className="h-7 px-1.5 py-0.5 text-[11px]"
            value=""
            onChange={(e) => {
              const raw = e.target.value;
              void applyBulk({
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
          <ConsoleSelect
            aria-label="Apply data type"
            className="h-7 px-1.5 py-0.5 text-[11px]"
            value=""
            onChange={(e) => {
              const raw = e.target.value;
              void applyBulk({ dataType: raw === '' ? null : (raw as GraphqlSignalDataType) });
            }}
          >
            <option value="">Data type…</option>
            {DATA_TYPES.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </ConsoleSelect>
          <ConsoleSelect
            aria-label="Apply label"
            className="h-7 px-1.5 py-0.5 text-[11px]"
            value=""
            onChange={(e) => {
              const name = e.target.value;
              if (!name) return;
              const targets = [...selected].map(parseRowKey);
              for (const target of targets) {
                const row = rows.find(
                  (r) => r.serverId === target.serverId && r.nodeId === target.nodeId,
                );
                const next = Array.from(new Set([...(row?.labels ?? []), name]));
                void applyPatch(target.serverId, target.nodeId, { labels: next });
              }
            }}
          >
            <option value="">Label…</option>
            {labels.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </ConsoleSelect>
          <BtnGhost className="px-2 py-1 text-[11px]" onClick={() => setSelected(new Set())}>
            Clear
          </BtnGhost>
        </div>
      )}

      {otherFor && (
        <div className="flex flex-wrap items-center gap-1.5 rounded-md border border-border bg-muted/40 px-2 py-1.5">
          <span className="text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
            New Unit of Measure
          </span>
          <input
            aria-label="New Unit of Measure"
            value={otherSymbol}
            onChange={(e) => setOtherSymbol(e.target.value)}
            className="h-7 w-28 rounded-md border border-border bg-background px-2 font-mono text-xs text-foreground focus:border-[#FF7A00]/50 focus:outline-none focus:ring-1 focus:ring-[#FF7A00]/30"
            placeholder="NTU"
          />
          <BtnGhost
            className="px-2 py-1 text-[11px]"
            onClick={() => {
              if (otherFor === 'bulk') void persistOtherUnit('bulk');
              else void persistOtherUnit(parseRowKey(otherFor));
            }}
          >
            Confirm
          </BtnGhost>
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
      ) : loadError ? null : filtered.length === 0 ? (
        <ConsoleCard padding="md" className="text-sm text-muted-foreground">
          {rows.length === 0 ? EMPTY_COPY : 'No signals match this search.'}
        </ConsoleCard>
      ) : (
        <ConsoleCard padding="none" className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1080px] border-collapse text-left text-sm">
              <thead className="border-b border-border bg-muted/50 text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
                <tr>
                  <th className="w-8 px-3 py-2">
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
                  <th className="px-3 py-2">Display name</th>
                  <th className="px-3 py-2">Server</th>
                  <th className="px-3 py-2">Asset</th>
                  <th className="px-3 py-2">Unit of Measure</th>
                  <th className="px-3 py-2">Class</th>
                  <th className="px-3 py-2">Data type</th>
                  <th className="px-3 py-2">Labels</th>
                  <th className="px-3 py-2">Subscribed</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border text-xs">
                {filtered.map((row) => {
                  const key = rowKey(row);
                  return (
                    <tr key={key} className="hover:bg-muted/60">
                      <td className="px-3 py-1.5">
                        <input
                          type="checkbox"
                          aria-label={`Select ${row.displayName}`}
                          checked={selected.has(key)}
                          onChange={(e) => toggleSelected(key, e.target.checked)}
                        />
                      </td>
                      <td className="px-3 py-1.5">
                        <button
                          type="button"
                          onClick={() => setOpenSignal(row)}
                          className="font-heading text-left font-semibold text-foreground hover:text-[#FF7A00] hover:underline"
                        >
                          {row.displayName}
                        </button>
                      </td>
                      <td className="px-3 py-1.5 text-muted-foreground">{row.serverName}</td>
                      <td className="px-3 py-1.5">
                        <ConsoleSelect
                          aria-label="Asset"
                          className="h-7 max-w-[14rem] px-1.5 py-0.5 text-[11px]"
                          value={row.assetId != null ? String(row.assetId) : ''}
                          onChange={(e) => {
                            const raw = e.target.value;
                            void applyPatch(row.serverId, row.nodeId, {
                              assetId: raw === '' ? null : Number(raw),
                            });
                          }}
                        >
                          <option value="">—</option>
                          {assets.map((asset) => (
                            <option key={asset.id} value={String(asset.id)}>
                              {asset.path}
                            </option>
                          ))}
                        </ConsoleSelect>
                      </td>
                      <td className="px-3 py-1.5">
                        {unitSelect(
                          'Unit of Measure',
                          row.unitOfMeasure ?? '',
                          (symbol) =>
                            void applyPatch(row.serverId, row.nodeId, { unitOfMeasure: symbol }),
                          key,
                        )}
                      </td>
                      <td className="px-3 py-1.5">
                        <ConsoleSelect
                          aria-label="Class"
                          className="h-7 px-1.5 py-0.5 text-[11px]"
                          value={row.semanticClass ?? ''}
                          onChange={(e) => {
                            const raw = e.target.value;
                            void applyPatch(row.serverId, row.nodeId, {
                              semanticClass:
                                raw === '' ? null : (raw as GraphqlSignalSemanticClass),
                            });
                          }}
                        >
                          <option value="">—</option>
                          {SEMANTIC_CLASSES.map((cls) => (
                            <option key={cls} value={cls}>
                              {cls}
                            </option>
                          ))}
                        </ConsoleSelect>
                      </td>
                      <td className="px-3 py-1.5">
                        <ConsoleSelect
                          aria-label="Data type"
                          className="h-7 px-1.5 py-0.5 text-[11px]"
                          value={row.dataType ?? ''}
                          onChange={(e) => {
                            const raw = e.target.value;
                            void applyPatch(row.serverId, row.nodeId, {
                              dataType: raw === '' ? null : (raw as GraphqlSignalDataType),
                            });
                          }}
                        >
                          <option value="">—</option>
                          {DATA_TYPES.map((type) => (
                            <option key={type} value={type}>
                              {type}
                            </option>
                          ))}
                        </ConsoleSelect>
                      </td>
                      <td className="px-3 py-1.5">
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
                            className="h-7 w-[7.5rem] px-1.5 py-0.5 text-[11px]"
                            value=""
                            onChange={(e) => {
                              const name = e.target.value;
                              if (!name) return;
                              const next = Array.from(new Set([...(row.labels ?? []), name]));
                              void applyPatch(row.serverId, row.nodeId, { labels: next });
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
                          </ConsoleSelect>
                        </div>
                      </td>
                      <td className="px-3 py-1.5 font-mono text-[11px] text-muted-foreground">
                        {row.subscribed ? 'Yes' : 'No'}
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
            setRows((prev) =>
              prev.filter((row) => !(row.serverId === serverIdValue && row.nodeId === nodeId)),
            );
            setSelected((prev) => {
              const next = new Set(prev);
              next.delete(rowKey({ serverId: serverIdValue, nodeId }));
              return next;
            });
            setOpenSignal(null);
          }}
        />
      )}
    </div>
  );
};

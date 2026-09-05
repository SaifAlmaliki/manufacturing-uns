import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, ChevronRight, Folder, FolderOpen, Radio, RefreshCw, X } from 'lucide-react';
import type {
  GraphqlConnectivityServer,
  GraphqlConnectivityTag,
  GraphqlOpcUaBrowseNode,
  GraphqlOpcUaDataValue,
} from '../../services/graphql/types';
import { unsGraphQLClient } from '../../services/graphql/client';
import { formatBrowseClock } from '../../lib/connectivity/map-servers';
import { BtnGhost, BtnPrimary } from '../ui/console-ui';

interface BrowseDataDrawerProps {
  server: GraphqlConnectivityServer;
  onClose: () => void;
  onSubscribed: (server: GraphqlConnectivityServer) => void;
}

interface RowState {
  nodeId: string;
  browsePath: string;
  displayName: string;
  mqttTopic: string;
  subscribed: boolean;
  value: unknown;
  dataType: string | null;
  sourceTimestamp: string | null;
  serverTimestamp: string | null;
  status: string;
}

function uniqueDiscovered(nodes: GraphqlOpcUaBrowseNode[]): GraphqlOpcUaBrowseNode[] {
  const seen = new Set<string>();
  return nodes.filter((node) => {
    if (seen.has(node.nodeId)) return false;
    seen.add(node.nodeId);
    return true;
  });
}

function subscribedTags(tags: GraphqlConnectivityTag[]): GraphqlConnectivityTag[] {
  return tags.filter((tag) => tag.subscribed);
}

function nodesFromTags(tags: GraphqlConnectivityTag[]): GraphqlOpcUaBrowseNode[] {
  return tags.map((tag) => ({
    nodeId: tag.nodeId,
    browseName: tag.displayName,
    displayName: tag.displayName,
    browsePath: tag.browsePath,
    nodeClass: 'Variable',
    hasChildren: false,
  }));
}

function mergeRows(
  discovered: GraphqlOpcUaBrowseNode[],
  tags: GraphqlConnectivityServer['tags'],
  values: GraphqlOpcUaDataValue[],
): RowState[] {
  const byNodeId = new Map<string, GraphqlOpcUaDataValue>();
  for (const v of values) byNodeId.set(v.nodeId, v);
  const tagByNodeId = new Map<string, (typeof tags)[number]>();
  for (const t of tags) tagByNodeId.set(t.nodeId, t);
  return uniqueDiscovered(discovered).map((node) => {
    const tag = tagByNodeId.get(node.nodeId);
    const value = byNodeId.get(node.nodeId);
    return {
      nodeId: node.nodeId,
      browsePath: node.browsePath,
      displayName: node.displayName,
      mqttTopic: tag?.mqttTopic ?? node.browsePath,
      subscribed: tag?.subscribed ?? false,
      value: value?.value ?? null,
      dataType: value?.dataType ?? null,
      sourceTimestamp: value?.sourceTimestamp ?? null,
      serverTimestamp: value?.serverTimestamp ?? null,
      status: value?.status ?? '—',
    };
  });
}

interface AddressSpaceTreeProps {
  endpoint: string;
  selectedId: string | null;
  onSelect: (node: GraphqlOpcUaBrowseNode) => void;
  onError: (message: string) => void;
}

const AddressSpaceTree: React.FC<AddressSpaceTreeProps> = ({
  endpoint,
  selectedId,
  onSelect,
  onError,
}) => {
  const [roots, setRoots] = useState<GraphqlOpcUaBrowseNode[]>([]);
  const [childrenById, setChildrenById] = useState<Record<string, GraphqlOpcUaBrowseNode[]>>({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [loadingRoot, setLoadingRoot] = useState(true);
  const [loadingIds, setLoadingIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    setLoadingRoot(true);
    void (async () => {
      try {
        const nodes = await unsGraphQLClient.browseOpcUa(endpoint);
        if (!cancelled) setRoots(nodes);
      } catch (err) {
        if (!cancelled) onError(err instanceof Error ? err.message : 'Browse failed');
      } finally {
        if (!cancelled) setLoadingRoot(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [endpoint, onError]);

  const loadChildren = useCallback(
    async (nodeId: string) => {
      if (childrenById[nodeId] !== undefined) return;
      setLoadingIds((prev) => new Set(prev).add(nodeId));
      try {
        const kids = await unsGraphQLClient.browseOpcUa(endpoint, nodeId);
        setChildrenById((prev) => ({ ...prev, [nodeId]: kids }));
      } catch (err) {
        onError(err instanceof Error ? err.message : 'Browse failed');
      } finally {
        setLoadingIds((prev) => {
          const next = new Set(prev);
          next.delete(nodeId);
          return next;
        });
      }
    },
    [childrenById, endpoint, onError],
  );

  const toggle = (node: GraphqlOpcUaBrowseNode) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(node.nodeId)) {
        next.delete(node.nodeId);
        return next;
      }
      next.add(node.nodeId);
      return next;
    });
    if (!expanded.has(node.nodeId) && node.hasChildren) {
      void loadChildren(node.nodeId);
    }
  };

  const renderNode = (node: GraphqlOpcUaBrowseNode, level: number) => {
    const isExpanded = expanded.has(node.nodeId);
    const isSelected = selectedId === node.nodeId;
    const kids = childrenById[node.nodeId];
    return (
      <div key={node.nodeId} className="select-none">
        <div
          style={{ paddingLeft: `${level * 14 + 8}px` }}
          className={`flex items-center gap-1 rounded-lg px-1.5 py-1 text-sm ${
            isSelected
              ? 'bg-[#FF7A00]/15 text-[#FF7A00]'
              : 'text-zinc-300 hover:bg-zinc-800/60 hover:text-white'
          }`}
        >
          {node.hasChildren ? (
            <button
              type="button"
              aria-label={isExpanded ? `Collapse ${node.displayName}` : `Expand ${node.displayName}`}
              onClick={() => toggle(node)}
              className="rounded p-0.5 text-zinc-500 hover:text-[#FF7A00]"
            >
              {isExpanded ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
            </button>
          ) : (
            <span className="w-4" />
          )}
          <button
            type="button"
            onClick={() => {
              onSelect(node);
              if (node.hasChildren && !expanded.has(node.nodeId)) toggle(node);
            }}
            className="flex min-w-0 flex-1 items-center gap-2 text-left"
          >
            {isExpanded ? (
              <FolderOpen className="size-3.5 shrink-0 text-[#FF7A00]" />
            ) : (
              <Folder className="size-3.5 shrink-0 text-zinc-500" />
            )}
            <span className="truncate">{node.displayName || node.browseName}</span>
          </button>
        </div>
        {isExpanded && (
          <div className="ml-3 border-l border-zinc-800">
            {loadingIds.has(node.nodeId) && (
              <div className="px-3 py-1 text-[11px] text-zinc-500">Loading…</div>
            )}
            {kids?.map((child) => renderNode(child, level + 1))}
          </div>
        )}
      </div>
    );
  };

  if (loadingRoot) {
    return <div className="p-4 text-xs text-zinc-500">Loading address space…</div>;
  }
  if (roots.length === 0) {
    return <div className="p-4 text-xs text-zinc-500">No nodes under Objects.</div>;
  }
  return <div className="p-1">{roots.map((node) => renderNode(node, 0))}</div>;
};

export const BrowseDataDrawer: React.FC<BrowseDataDrawerProps> = ({ server, onClose, onSubscribed }) => {
  const [selected, setSelected] = useState<GraphqlOpcUaBrowseNode | null>(null);
  const [discovered, setDiscovered] = useState<GraphqlOpcUaBrowseNode[]>([]);
  const [rows, setRows] = useState<RowState[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [subscribing, setSubscribing] = useState(false);
  const [busyNodeId, setBusyNodeId] = useState<string | null>(null);
  const [draftTopics, setDraftTopics] = useState<Record<string, string>>({});
  const [editingTopicId, setEditingTopicId] = useState<string | null>(null);
  const unsubRef = useRef<(() => void) | null>(null);
  const tagsRef = useRef(server.tags);
  tagsRef.current = server.tags;

  const catalogSubscribed = useMemo(() => subscribedTags(server.tags), [server.tags]);

  const emitServerTags = useCallback(
    (tags: GraphqlConnectivityTag[]) => {
      onSubscribed({ ...server, tags });
    },
    [onSubscribed, server],
  );

  const handleTreeError = useCallback((message: string) => {
    setError(message);
  }, []);

  const applyLiveValues = useCallback(
    (nodes: GraphqlOpcUaBrowseNode[], tags: GraphqlConnectivityTag[], cancelled: () => boolean) => {
      const initial = mergeRows(nodes, tags, []);
      setRows(initial);
      const drafts: Record<string, string> = {};
      for (const r of initial) drafts[r.nodeId] = r.mqttTopic;
      setDraftTopics(drafts);
      if (nodes.length === 0) return;
      const nodeIds = nodes.map((n) => n.nodeId);
      void unsGraphQLClient
        .readOpcUaNodes(server.endpoint, nodeIds)
        .then((values) => {
          if (cancelled()) return;
          setRows(mergeRows(nodes, tags, values));
        })
        .catch(() => {
          // Value reads can fail on demo nodes after the list is already on screen.
        });
      if (unsubRef.current) {
        unsubRef.current();
        unsubRef.current = null;
      }
      unsubRef.current = unsGraphQLClient.subscribeOpcUaDataChanges(
        server.endpoint,
        nodeIds,
        (value: GraphqlOpcUaDataValue) => {
          setRows((prev) =>
            prev.map((r) =>
              r.nodeId === value.nodeId
                ? {
                    ...r,
                    value: value.value,
                    dataType: value.dataType,
                    sourceTimestamp: value.sourceTimestamp,
                    serverTimestamp: value.serverTimestamp,
                    status: value.status,
                  }
                : r,
            ),
          );
        },
      );
    },
    [server.endpoint],
  );

  useEffect(() => {
    if (selected) return;
    let cancelled = false;
    const nodes = nodesFromTags(catalogSubscribed);
    setDiscovered(nodes);
    setLoading(false);
    applyLiveValues(nodes, server.tags, () => cancelled);
    return () => {
      cancelled = true;
      if (unsubRef.current) {
        unsubRef.current();
        unsubRef.current = null;
      }
    };
  }, [applyLiveValues, catalogSubscribed, selected, server.tags]);

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const nodes = uniqueDiscovered(
          await unsGraphQLClient.discoverOpcUaVariables(server.endpoint, selected.nodeId),
        );
        if (cancelled) return;
        setDiscovered(nodes);
        applyLiveValues(nodes, tagsRef.current, () => cancelled);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Browse failed');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
      if (unsubRef.current) {
        unsubRef.current();
        unsubRef.current = null;
      }
    };
  }, [applyLiveValues, selected, server.endpoint]);

  const nodeIds = useMemo(() => discovered.map((n) => n.nodeId), [discovered]);

  const handleSubscribe = async () => {
    if (!selected) return;
    setSubscribing(true);
    setError(null);
    try {
      const tags = await unsGraphQLClient.subscribeOpcUaVariables(server.id, selected.nodeId);
      const tagMap = new Map(tags.map((t) => [t.nodeId, t]));
      setRows((prev) =>
        prev.map((r) => {
          const tag = tagMap.get(r.nodeId);
          return tag
            ? { ...r, subscribed: true, mqttTopic: tag.mqttTopic }
            : { ...r, subscribed: false };
        }),
      );
      if (nodeIds.length > 0) {
        if (unsubRef.current) {
          unsubRef.current();
          unsubRef.current = null;
        }
        unsubRef.current = unsGraphQLClient.subscribeOpcUaDataChanges(
          server.endpoint,
          nodeIds,
          (value: GraphqlOpcUaDataValue) => {
            setRows((prev) =>
              prev.map((r) =>
                r.nodeId === value.nodeId
                  ? {
                      ...r,
                      value: value.value,
                      dataType: value.dataType,
                      sourceTimestamp: value.sourceTimestamp,
                      serverTimestamp: value.serverTimestamp,
                      status: value.status,
                    }
                  : r,
              ),
            );
          },
        );
      }
      emitServerTags(
        tags.map((t) => ({
          serverId: server.id,
          nodeId: t.nodeId,
          browsePath: t.browsePath,
          displayName: t.displayName,
          mqttTopic: t.mqttTopic,
          subscribed: t.subscribed,
        })),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Subscribe failed');
    } finally {
      setSubscribing(false);
    }
  };

  const handleTopicBlur = async (nodeId: string) => {
    const next = draftTopics[nodeId] ?? '';
    const current = rows.find((r) => r.nodeId === nodeId)?.mqttTopic ?? '';
    if (next.trim() === current.trim() || !next.trim()) return;
    setBusyNodeId(nodeId);
    try {
      const updated = await unsGraphQLClient.updateConnectivityTagTopic(
        server.id,
        nodeId,
        next.trim(),
      );
      setRows((prev) =>
        prev.map((r) =>
          r.nodeId === nodeId ? { ...r, mqttTopic: updated.mqttTopic, subscribed: true } : r,
        ),
      );
      emitServerTags(
        server.tags.some((t) => t.nodeId === nodeId)
          ? server.tags.map((t) =>
              t.nodeId === nodeId ? { ...t, mqttTopic: updated.mqttTopic, subscribed: true } : t,
            )
          : [
              ...server.tags,
              {
                serverId: server.id,
                nodeId,
                browsePath: rows.find((r) => r.nodeId === nodeId)?.browsePath ?? nodeId,
                displayName: rows.find((r) => r.nodeId === nodeId)?.displayName ?? nodeId,
                mqttTopic: updated.mqttTopic,
                subscribed: true,
              },
            ],
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Topic was not updated');
    } finally {
      setBusyNodeId(null);
    }
  };

  const handleSubscribeRow = async (nodeId: string) => {
    setBusyNodeId(nodeId);
    setError(null);
    try {
      const tags = await unsGraphQLClient.subscribeOpcUaVariables(server.id, nodeId);
      const tag = tags.find((t) => t.nodeId === nodeId);
      setRows((prev) =>
        prev.map((r) =>
          r.nodeId === nodeId
            ? {
                ...r,
                subscribed: true,
                mqttTopic: tag?.mqttTopic ?? r.mqttTopic,
              }
            : r,
        ),
      );
      emitServerTags(
        tags.map((t) => ({
          serverId: server.id,
          nodeId: t.nodeId,
          browsePath: t.browsePath,
          displayName: t.displayName,
          mqttTopic: t.mqttTopic,
          subscribed: t.subscribed,
        })),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Subscribe failed');
    } finally {
      setBusyNodeId(null);
    }
  };

  const handleUnsubscribe = async (nodeId: string) => {
    setBusyNodeId(nodeId);
    try {
      await unsGraphQLClient.unsubscribeConnectivityTag(server.id, nodeId);
      emitServerTags(
        server.tags.map((t) => (t.nodeId === nodeId ? { ...t, subscribed: false } : t)),
      );
      setRows((prev) =>
        selected
          ? prev.map((r) => (r.nodeId === nodeId ? { ...r, subscribed: false } : r))
          : prev.filter((r) => r.nodeId !== nodeId),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unsubscribe failed');
    } finally {
      setBusyNodeId(null);
    }
  };

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="flex h-[min(88vh,860px)] w-[min(1200px,96vw)] flex-col overflow-hidden rounded-2xl border border-zinc-800 bg-[#111114] shadow-2xl"
        role="dialog"
        aria-label="Browse OPC UA data"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex shrink-0 items-center justify-between gap-3 border-b border-zinc-800 px-4 py-3">
          <div className="min-w-0">
            <div className="text-[10px] uppercase tracking-wider text-zinc-500">Browse data</div>
            <div className="truncate text-sm font-semibold text-white">{server.name}</div>
            <div className="truncate text-xs text-zinc-500">
              {selected
                ? selected.browsePath || selected.displayName
                : catalogSubscribed.length > 0
                  ? `${catalogSubscribed.length} subscribed signal${catalogSubscribed.length === 1 ? '' : 's'}`
                  : 'Pick a folder in the address space'}
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <BtnPrimary
              onClick={() => void handleSubscribe()}
              disabled={subscribing || loading || !selected || discovered.length === 0}
              className="px-3 py-1.5 text-xs"
            >
              <RefreshCw className="size-3.5" />
              {subscribing ? 'Subscribing…' : selected ? 'Subscribe folder' : 'Subscribe'}
            </BtnPrimary>
            <BtnGhost onClick={onClose} aria-label="Close" className="px-2 py-1.5">
              <X className="size-4" />
            </BtnGhost>
          </div>
        </div>

        {error && (
          <div className="shrink-0 border-b border-rose-500/30 bg-rose-500/10 px-4 py-2 text-xs text-rose-200">
            {error}
          </div>
        )}

        <div className="flex min-h-0 flex-1">
          <div className="flex w-64 shrink-0 flex-col border-r border-zinc-800">
            <div className="shrink-0 border-b border-zinc-800 px-3 py-2 text-[10px] uppercase tracking-wider text-zinc-500">
              Address space
            </div>
            <div className="min-h-0 flex-1 overflow-auto">
              <button
                type="button"
                onClick={() => setSelected(null)}
                className={`m-1 flex w-[calc(100%-0.5rem)] items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm ${
                  selected === null
                    ? 'bg-[#FF7A00]/15 text-[#FF7A00]'
                    : 'text-zinc-300 hover:bg-zinc-800/60 hover:text-white'
                }`}
              >
                <Radio className="size-3.5 shrink-0" />
                <span className="min-w-0 flex-1 truncate">Subscribed</span>
                {catalogSubscribed.length > 0 && (
                  <span className="tabular-nums text-[11px] text-zinc-500">{catalogSubscribed.length}</span>
                )}
              </button>
              <AddressSpaceTree
                endpoint={server.endpoint}
                selectedId={selected?.nodeId ?? null}
                onSelect={setSelected}
                onError={handleTreeError}
              />
            </div>
          </div>

          <div className="min-h-0 min-w-0 flex-1 overflow-auto">
            {!selected && catalogSubscribed.length === 0 ? (
              <div className="p-8 text-center text-sm text-zinc-500">
                Select a folder to list its signals — same as dragging a section in UA Expert.
                Subscribed signals stay in the catalog and show here when you reopen this
                server.
              </div>
            ) : loading ? (
              <div className="p-8 text-center text-sm text-zinc-500">
                Discovering signals under {selected.displayName || selected.browseName}…
              </div>
            ) : rows.length === 0 ? (
              <div className="p-8 text-center text-sm text-zinc-500">No signals under this node.</div>
            ) : (
              <table className="w-full border-collapse text-left text-sm">
                <thead className="sticky top-0 bg-zinc-900/95 text-[10px] uppercase text-zinc-500">
                  <tr>
                    <th className="px-3 py-2 font-medium">Signal</th>
                    <th className="px-3 py-2 font-medium">MQTT topic</th>
                    <th className="px-3 py-2 font-medium">Value</th>
                    <th className="px-3 py-2 font-medium">Quality</th>
                    <th className="w-[4.5rem] px-3 py-2 font-medium">Source</th>
                    <th className="w-[4.5rem] px-3 py-2 font-medium">Server</th>
                    <th className="w-24 px-3 py-2 text-right font-medium">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800/80 text-xs">
                  {rows.map((row) => (
                    <tr key={row.nodeId} className="hover:bg-zinc-800/30">
                      <td className="px-3 py-2 align-top">
                        <div className="font-medium text-white">{row.displayName}</div>
                        <div className="mt-0.5 break-all font-mono text-[11px] text-zinc-500">
                          {row.browsePath}
                        </div>
                      </td>
                      <td className="px-3 py-2 align-top">
                        {editingTopicId === row.nodeId ? (
                          <input
                            type="text"
                            aria-label={`MQTT topic for ${row.displayName}`}
                            value={draftTopics[row.nodeId] ?? row.mqttTopic}
                            onChange={(e) =>
                              setDraftTopics((prev) => ({ ...prev, [row.nodeId]: e.target.value }))
                            }
                            onBlur={() => {
                              void handleTopicBlur(row.nodeId);
                              setEditingTopicId(null);
                            }}
                            disabled={busyNodeId === row.nodeId}
                            autoFocus
                            className="w-full rounded-md border border-[#FF7A00]/50 bg-zinc-900/80 px-2 py-1.5 font-mono text-xs text-[#FF7A00] focus:outline-none focus:ring-1 focus:ring-[#FF7A00]/30 disabled:opacity-50"
                          />
                        ) : (
                          <div className="flex items-start gap-2">
                            <div className="min-w-0 flex-1 break-all font-mono text-xs leading-5 text-[#FF7A00]">
                              {row.mqttTopic}
                            </div>
                            <button
                              type="button"
                              onClick={() => {
                                setDraftTopics((prev) => ({
                                  ...prev,
                                  [row.nodeId]: prev[row.nodeId] ?? row.mqttTopic,
                                }));
                                setEditingTopicId(row.nodeId);
                              }}
                              className="shrink-0 text-[11px] text-zinc-400 underline-offset-2 hover:text-[#FF7A00] hover:underline"
                            >
                              Edit
                            </button>
                          </div>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 align-top font-mono text-zinc-200">
                        {row.value === null || row.value === undefined ? '—' : String(row.value)}
                        {row.dataType ? (
                          <span className="ml-1 text-[10px] text-zinc-500">{row.dataType}</span>
                        ) : null}
                      </td>
                      <td className="px-3 py-2 align-top">
                        <span
                          className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                            row.status === 'Good'
                              ? 'bg-emerald-500/15 text-emerald-300'
                              : row.status === 'Bad'
                                ? 'bg-rose-500/15 text-rose-300'
                                : 'bg-zinc-700/40 text-zinc-300'
                          }`}
                        >
                          {row.status}
                        </span>
                      </td>
                      <td
                        className="whitespace-nowrap px-3 py-2 align-top tabular-nums text-[11px] text-zinc-500"
                        title={row.sourceTimestamp ?? undefined}
                      >
                        {formatBrowseClock(row.sourceTimestamp)}
                      </td>
                      <td
                        className="whitespace-nowrap px-3 py-2 align-top tabular-nums text-[11px] text-zinc-500"
                        title={row.serverTimestamp ?? undefined}
                      >
                        {formatBrowseClock(row.serverTimestamp)}
                      </td>
                      <td className="px-3 py-2 text-right align-top">
                        {row.subscribed ? (
                          <button
                            type="button"
                            onClick={() => void handleUnsubscribe(row.nodeId)}
                            disabled={busyNodeId === row.nodeId}
                            className="rounded-md border border-zinc-700 px-2 py-1 text-[11px] text-zinc-300 hover:border-rose-500/50 hover:text-rose-300 disabled:opacity-50"
                          >
                            Unsubscribe
                          </button>
                        ) : (
                          <button
                            type="button"
                            onClick={() => void handleSubscribeRow(row.nodeId)}
                            disabled={busyNodeId === row.nodeId}
                            className="rounded-md border border-[#FF7A00]/40 px-2 py-1 text-[11px] text-[#FF7A00] hover:bg-[#FF7A00]/10 disabled:opacity-50"
                          >
                            Subscribe
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

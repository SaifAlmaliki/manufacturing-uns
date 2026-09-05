import React, { useEffect, useMemo, useRef, useState } from 'react';
import { X, RefreshCw } from 'lucide-react';
import type {
  GraphqlConnectivityServer,
  GraphqlOpcUaBrowseNode,
  GraphqlOpcUaDataValue,
} from '../../services/graphql/types';
import { unsGraphQLClient } from '../../services/graphql/client';
import { BtnGhost, BtnPrimary, ConsoleCard, consoleTokens } from '../ui/console-ui';

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

function mergeRows(
  discovered: GraphqlOpcUaBrowseNode[],
  tags: GraphqlConnectivityServer['tags'],
  values: GraphqlOpcUaDataValue[],
): RowState[] {
  const byNodeId = new Map<string, GraphqlOpcUaDataValue>();
  for (const v of values) byNodeId.set(v.nodeId, v);
  const tagByNodeId = new Map<string, (typeof tags)[number]>();
  for (const t of tags) tagByNodeId.set(t.nodeId, t);
  return discovered.map((node) => {
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

export const BrowseDataDrawer: React.FC<BrowseDataDrawerProps> = ({ server, onClose, onSubscribed }) => {
  const [discovered, setDiscovered] = useState<GraphqlOpcUaBrowseNode[]>([]);
  const [rows, setRows] = useState<RowState[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [subscribing, setSubscribing] = useState(false);
  const [busyNodeId, setBusyNodeId] = useState<string | null>(null);
  const [draftTopics, setDraftTopics] = useState<Record<string, string>>({});
  const unsubRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const nodes = await unsGraphQLClient.discoverOpcUaVariables(server.endpoint);
        if (cancelled) return;
        setDiscovered(nodes);
        const initial = mergeRows(nodes, server.tags, []);
        setRows(initial);
        const drafts: Record<string, string> = {};
        for (const r of initial) drafts[r.nodeId] = r.mqttTopic;
        setDraftTopics(drafts);
        if (nodes.length > 0) {
          void unsGraphQLClient
            .readOpcUaNodes(
              server.endpoint,
              nodes.map((n) => n.nodeId),
            )
            .then((values) => {
              if (cancelled) return;
              setRows(mergeRows(nodes, server.tags, values));
            });
        }
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
  }, [server.endpoint, server.tags]);

  const nodeIds = useMemo(() => discovered.map((n) => n.nodeId), [discovered]);

  const handleSubscribe = async () => {
    setSubscribing(true);
    setError(null);
    try {
      const tags = await unsGraphQLClient.subscribeOpcUaVariables(server.id);
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
      onSubscribed({
        ...server,
        tags: tags.map((t) => ({
          serverId: server.id,
          nodeId: t.nodeId,
          browsePath: t.browsePath,
          displayName: t.displayName,
          mqttTopic: t.mqttTopic,
          subscribed: t.subscribed,
        })),
      });
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
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Topic was not updated');
    } finally {
      setBusyNodeId(null);
    }
  };

  const handleUnsubscribe = async (nodeId: string) => {
    setBusyNodeId(nodeId);
    try {
      await unsGraphQLClient.unsubscribeConnectivityTag(server.id, nodeId);
      setRows((prev) =>
        prev.map((r) => (r.nodeId === nodeId ? { ...r, subscribed: false } : r)),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unsubscribe failed');
    } finally {
      setBusyNodeId(null);
    }
  };

  return (
    <aside
      className="fixed inset-y-0 right-0 z-40 flex w-full max-w-5xl flex-col border-l border-zinc-800 bg-[#111114] shadow-2xl"
      role="dialog"
      aria-label="Browse OPC UA data"
    >
      <div className="flex shrink-0 items-center justify-between border-b border-zinc-800 px-4 py-3">
        <div className="min-w-0">
          <div className="text-[10px] uppercase tracking-wider text-zinc-500">Browse data</div>
          <div className="truncate text-sm font-semibold text-white">{server.name}</div>
          <div className="truncate font-mono text-[11px] text-zinc-500">{server.endpoint}</div>
        </div>
        <div className="flex items-center gap-2">
          <BtnPrimary
            onClick={() => void handleSubscribe()}
            disabled={subscribing || loading || discovered.length === 0}
            className="px-3 py-1.5 text-xs"
          >
            <RefreshCw className="size-3.5" />
            {subscribing ? 'Subscribing…' : 'Subscribe'}
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

      <div className="min-h-0 flex-1 overflow-auto">
        {loading ? (
          <div className="p-8 text-center text-sm text-zinc-500">Browsing OPC UA variables…</div>
        ) : rows.length === 0 ? (
          <div className="p-8 text-center text-sm text-zinc-500">
            No variables discovered under Objects on this endpoint.
          </div>
        ) : (
          <table className="w-full min-w-[1100px] border-collapse text-left text-xs">
            <thead className="sticky top-0 bg-zinc-900/95 text-[10px] uppercase text-zinc-500">
              <tr>
                <th className="px-3 py-2 font-medium">NodeId</th>
                <th className="px-3 py-2 font-medium">Browse path</th>
                <th className="px-3 py-2 font-medium">MQTT topic</th>
                <th className="px-3 py-2 font-medium">Display name</th>
                <th className="px-3 py-2 font-medium">Value</th>
                <th className="px-3 py-2 font-medium">Data type</th>
                <th className="px-3 py-2 font-medium">Source time</th>
                <th className="px-3 py-2 font-medium">Server time</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800/80">
              {rows.map((row) => (
                <tr key={row.nodeId} className="hover:bg-zinc-800/30">
                  <td className="px-3 py-2 font-mono text-[11px] text-zinc-300">{row.nodeId}</td>
                  <td className="px-3 py-2 font-mono text-[11px] text-zinc-400">{row.browsePath}</td>
                  <td className="px-3 py-2">
                    <input
                      type="text"
                      value={draftTopics[row.nodeId] ?? row.mqttTopic}
                      onChange={(e) =>
                        setDraftTopics((prev) => ({ ...prev, [row.nodeId]: e.target.value }))
                      }
                      onBlur={() => void handleTopicBlur(row.nodeId)}
                      disabled={busyNodeId === row.nodeId}
                      className={`w-full rounded-md border border-zinc-800 bg-zinc-900/80 px-2 py-1 font-mono text-[11px] text-[#FF7A00] focus:border-[#FF7A00]/50 focus:outline-none focus:ring-1 focus:ring-[#FF7A00]/30 disabled:opacity-50`}
                    />
                  </td>
                  <td className="px-3 py-2 text-zinc-300">{row.displayName}</td>
                  <td className="px-3 py-2 font-mono text-zinc-200">
                    {row.value === null || row.value === undefined ? '—' : String(row.value)}
                  </td>
                  <td className="px-3 py-2 text-zinc-400">{row.dataType ?? '—'}</td>
                  <td className="px-3 py-2 text-zinc-500">{row.sourceTimestamp ?? '—'}</td>
                  <td className="px-3 py-2 text-zinc-500">{row.serverTimestamp ?? '—'}</td>
                  <td className="px-3 py-2">
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
                  <td className="px-3 py-2 text-right">
                    {row.subscribed ? (
                      <button
                        type="button"
                        onClick={() => void handleUnsubscribe(row.nodeId)}
                        disabled={busyNodeId === row.nodeId}
                        className="rounded-md border border-zinc-700 px-2 py-1 text-[10px] text-zinc-300 hover:border-rose-500/50 hover:text-rose-300 disabled:opacity-50"
                      >
                        Unsubscribe
                      </button>
                    ) : (
                      <span className="text-[10px] text-zinc-600">not subscribed</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </aside>
  );
};

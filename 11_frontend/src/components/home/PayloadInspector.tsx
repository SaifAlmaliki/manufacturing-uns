import React, { useState } from 'react';
import {
  Copy,
  Check,
  Clock,
  History,
  Bookmark,
  BookmarkPlus,
  Radio,
  Tag,
  Server,
  Layers,
  ChevronRight,
  Filter,
  Gauge,
} from 'lucide-react';
import { useUNS } from '../../context/UNSContext';
import { JsonViewer } from '../common/JsonViewer';
import { getNodeRole, getNodeRoleLabel, hasLiveTelemetry, isNodeStale, isStaleCandidate } from '../../lib/uns/node-meta';
import { parseMetricNumber } from '../../lib/uns/telemetry-metrics';
import { useTheme } from '../../context/ThemeContext';
import { GRAFANA_DASHBOARDS, GrafanaEmbed, grafanaTopicFilter } from '../common/GrafanaEmbed';

export const PayloadInspector: React.FC = () => {
  const {
    selectedNode,
    jumpToHistorian,
    jumpToSparkplug,
    isBookmarked,
    addBookmark,
    removeBookmark,
    setFeedTopicFilter,
    settings,
  } = useUNS();
  const { isDark } = useTheme();

  const [copiedTopic, setCopiedTopic] = useState(false);

  if (!selectedNode) {
    return (
      <div
        id="payload-inspector-empty"
        className="flex h-full flex-col items-center justify-center bg-[#111114] p-8 text-center"
      >
        <Layers className="mb-3 size-10 text-zinc-700" />
        <h3 className="text-sm font-medium text-zinc-400">No topic selected</h3>
        <p className="mt-1 max-w-xs text-sm text-zinc-600">
          Select a node from the tree to inspect its live payload.
        </p>
      </div>
    );
  }

  const handleCopyTopic = () => {
    navigator.clipboard.writeText(selectedNode.topic);
    setCopiedTopic(true);
    setTimeout(() => setCopiedTopic(false), 1500);
  };

  const pathParts = selectedNode.topic.split('/');
  const bookmarked = isBookmarked(selectedNode.topic);
  const role = getNodeRole(selectedNode.nodeType);
  const live = hasLiveTelemetry(selectedNode.payload);
  const stale =
    isStaleCandidate(selectedNode) &&
    isNodeStale(selectedNode.lastUpdated, settings.staleThresholdMinutes || 5);

  // Extract key numeric telemetry properties for top parameter cards
  const numericMetrics: { key: string; value: number | string; unit?: string }[] = [];
  if (typeof selectedNode.payload === 'object' && selectedNode.payload !== null) {
    const payloadObj = selectedNode.payload as Record<string, unknown>;
    const value = parseMetricNumber(payloadObj.value);
    if (value !== undefined) {
      const unit =
        typeof payloadObj.unit === 'string'
          ? payloadObj.unit
          : selectedNode.name.toLowerCase().includes('temp')
            ? '°C'
            : selectedNode.name.toLowerCase().includes('press')
              ? 'psi'
              : selectedNode.name.toLowerCase().includes('flow')
                ? 'L/min'
                : '';
      numericMetrics.push({ key: 'value', value, unit });
    }
    for (const [k, v] of Object.entries(payloadObj)) {
      if (k === 'value' || k === 'unit') continue;
      const num = parseMetricNumber(v);
      if (num !== undefined) {
        numericMetrics.push({ key: k, value: num });
      }
    }
  }

  return (
    <div id="payload-inspector-panel" className="flex h-full flex-col overflow-hidden bg-[#111114] text-zinc-100">
      <div className="shrink-0 space-y-2 border-b border-zinc-800 p-3">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0 truncate text-sm font-medium text-white" title={selectedNode.topic}>
            {pathParts[pathParts.length - 1]}
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <button
              onClick={handleCopyTopic}
              className="rounded-lg p-1.5 text-zinc-500 hover:bg-zinc-800 hover:text-[#FF7A00]"
              title="Copy topic"
            >
              {copiedTopic ? <Check className="size-3.5 text-emerald-500" /> : <Copy className="size-3.5" />}
            </button>
            <button
              onClick={() => (bookmarked ? removeBookmark(selectedNode.topic) : addBookmark(selectedNode.topic))}
              className="rounded-lg p-1.5 text-zinc-500 hover:bg-zinc-800 hover:text-[#FF7A00]"
              title="Bookmark"
            >
              {bookmarked ? (
                <Bookmark className="size-3.5 fill-[#FF7A00] text-[#FF7A00]" />
              ) : (
                <BookmarkPlus className="size-3.5" />
              )}
            </button>
            <button
              onClick={() => jumpToHistorian(selectedNode.topic)}
              className="rounded-lg bg-[#FF7A00]/15 px-2 py-1 text-xs font-medium text-[#FF7A00] hover:bg-[#FF7A00]/25"
            >
              Historian
            </button>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3 text-xs text-zinc-500">
          <span className={live ? 'text-emerald-400' : 'text-zinc-600'}>{live ? 'Live' : 'No data'}</span>
          <span>·</span>
          <span>{selectedNode.publisher || 'No publisher'}</span>
          <span>·</span>
          <span className={stale ? 'text-amber-400' : 'text-zinc-400'}>
            {new Date(selectedNode.lastUpdated).toLocaleTimeString()}
          </span>
        </div>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto p-3">
        {/* Real-time Parameters Banner Grid */}
        {numericMetrics.length > 0 && (
          <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-3">
            <div className="mb-2 text-xs font-medium text-zinc-500">Live values</div>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {numericMetrics.slice(0, 6).map((m) => (
                <div key={m.key} className="rounded-xl border border-zinc-800 bg-[#111114] p-2">
                  <div className="truncate text-[10px] uppercase text-zinc-600">{m.key}</div>
                  <div className="mt-1 text-lg font-semibold tabular-nums text-[#FF7A00]">
                    {typeof m.value === 'number' ? m.value.toFixed(1) : m.value}
                    {m.unit && <span className="ml-1 text-xs text-zinc-500">{m.unit}</span>}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        <div id="payload-inspector-grafana-trend" className="h-80 overflow-hidden rounded-2xl border border-zinc-800">
          <GrafanaEmbed
            uid={GRAFANA_DASHBOARDS.process.uid}
            theme={isDark ? 'dark' : 'light'}
            title="Process Visualization"
            vars={{ topic: grafanaTopicFilter(selectedNode.topic) }}
            from="now-6h"
            to="now"
          />
        </div>

        <JsonViewer
          data={selectedNode.payload}
          title={`CURRENT PAYLOAD • ${selectedNode.name}`}
          maxHeight="max-h-[340px]"
        />

        {/* Properties Key-Value Table */}
        {selectedNode.properties && Object.keys(selectedNode.properties).length > 0 && (
          <div className="bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] rounded-lg overflow-hidden shadow-xs">
            <div className="px-3 py-1.5 bg-[#F8FAFC] dark:bg-[#111114] border-b border-[#E2E8F0] dark:border-[#1E293B] text-[10px] font-mono font-semibold text-[#475569] dark:text-[#94A3B8] flex items-center gap-1.5">
              <Tag className="w-3 h-3 text-amber-600 dark:text-[#FFC107]" />
              <span>NODE PROPERTIES</span>
            </div>
            <div className="divide-y divide-[#E2E8F0] dark:divide-[#1E293B] font-mono text-[10px]">
              {Object.entries(selectedNode.properties).map(([key, value]) => (
                <div key={key} className="flex items-center justify-between px-3 py-1.5 hover:bg-slate-50 dark:hover:bg-[#1E293B]/40">
                  <span className="text-[#64748B] dark:text-[#94A3B8]">{key}</span>
                  <span className="text-[#0F172A] dark:text-[#F8FAFC] font-semibold">{value}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Sparkplug Quick Check */}
        {selectedNode.topic.startsWith('spBv1.0/') && (
          <div className="p-3 rounded-lg bg-purple-50 dark:bg-[#111114] border border-purple-200 dark:border-[#A855F7]/40 flex items-center justify-between font-mono">
            <div className="flex items-center gap-2">
              <Radio className="w-4 h-4 text-purple-600 dark:text-[#A855F7]" />
              <div>
                <span className="text-purple-900 dark:text-[#A855F7] font-semibold text-[11px]">Sparkplug B Protobuf Telemetry</span>
                <p className="text-[10px] text-purple-700 dark:text-[#94A3B8]">
                  Decoded by 07_uns_graphql Sparkplug mapper.
                </p>
              </div>
            </div>
            <button
              onClick={() => jumpToSparkplug(selectedNode.name)}
              className="px-2.5 py-1 rounded bg-purple-600 hover:bg-purple-700 dark:bg-[#A855F7] dark:hover:bg-[#9333EA] text-white font-mono text-[10px] font-medium transition-colors cursor-pointer"
            >
              Open in Sparkplug
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

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
  Activity,
  Gauge,
} from 'lucide-react';
import { useUNS } from '../../context/UNSContext';
import { JsonViewer } from '../common/JsonViewer';

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

  const [copiedTopic, setCopiedTopic] = useState(false);

  if (!selectedNode) {
    return (
      <div
        id="payload-inspector-empty"
        className="flex flex-col items-center justify-center h-full bg-[#FFFFFF] dark:bg-[#050505] text-[#64748B] p-8 text-center"
      >
        <Layers className="w-10 h-10 text-[#CBD5E1] dark:text-[#334155] mb-3" />
        <h3 className="text-[#475569] dark:text-[#94A3B8] font-semibold text-xs font-mono">NO TOPIC SELECTED</h3>
        <p className="text-[11px] text-[#64748B] max-w-sm mt-1 font-mono">
          Select any ISA-95 node from the namespace hierarchy on the left to inspect its live telemetry snapshot and parameters.
        </p>
      </div>
    );
  }

  const handleCopyTopic = () => {
    navigator.clipboard.writeText(selectedNode.topic);
    setCopiedTopic(true);
    setTimeout(() => setCopiedTopic(false), 1500);
  };

  const isStale = (isoString: string) => {
    const diffMs = Date.now() - new Date(isoString).getTime();
    return diffMs > (settings.staleThresholdMinutes || 5) * 60 * 1000;
  };

  const pathParts = selectedNode.topic.split('/');
  const bookmarked = isBookmarked(selectedNode.topic);
  const stale = isStale(selectedNode.lastUpdated);

  // Extract key numeric telemetry properties for top parameter cards
  const numericMetrics: { key: string; value: number | string; unit?: string }[] = [];
  if (typeof selectedNode.payload === 'object' && selectedNode.payload !== null) {
    for (const [k, v] of Object.entries(selectedNode.payload)) {
      if (typeof v === 'number') {
        let unit = '';
        if (k.toLowerCase().includes('temp')) unit = '°C';
        else if (k.toLowerCase().includes('press')) unit = 'bar';
        else if (k.toLowerCase().includes('speed') || k.toLowerCase().includes('vel')) unit = 'RPM';
        else if (k.toLowerCase().includes('rate') || k.toLowerCase().includes('flow')) unit = 'kg/h';
        else if (k.toLowerCase().includes('pct') || k.toLowerCase().includes('percent')) unit = '%';
        numericMetrics.push({ key: k, value: v, unit });
      }
    }
  }

  return (
    <div id="payload-inspector-panel" className="flex flex-col h-full bg-[#F8FAFC] dark:bg-[#050505] overflow-hidden">
      {/* Top Header: ISA-95 Breadcrumbs & Quick Actions */}
      <div className="p-3 bg-white dark:bg-[#111114] border-b border-[#E2E8F0] dark:border-[#1E293B] space-y-2 shrink-0">
        {/* Breadcrumb Path */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1 overflow-x-auto text-[10px] font-mono py-0.5 max-w-xl scrollbar-none">
            {pathParts.map((part, idx) => (
              <React.Fragment key={idx}>
                {idx > 0 && <ChevronRight className="w-3 h-3 text-[#94A3B8] dark:text-[#475569] shrink-0" />}
                <span
                  className={`px-1.5 py-0.5 rounded ${
                    idx === pathParts.length - 1
                      ? 'bg-amber-50 dark:bg-[#1E293B] text-amber-900 dark:text-[#FFC107] font-semibold border border-amber-300 dark:border-[#334155]'
                      : 'text-[#475569] dark:text-[#94A3B8] bg-slate-100 dark:bg-[#0B0B0C]'
                  }`}
                >
                  {part}
                </span>
              </React.Fragment>
            ))}
          </div>

          {/* Action Buttons */}
          <div className="flex items-center gap-1.5 shrink-0">
            <button
              onClick={handleCopyTopic}
              className="flex items-center gap-1 px-2 py-0.5 rounded bg-white dark:bg-[#1E293B] hover:bg-slate-100 dark:hover:bg-[#334155] text-[#0F172A] dark:text-[#E2E8F0] text-[10px] font-mono border border-[#CBD5E1] dark:border-[#334155] transition-colors cursor-pointer"
              title="Copy Topic Path"
            >
              {copiedTopic ? <Check className="w-3 h-3 text-emerald-600 dark:text-[#10B981]" /> : <Copy className="w-3 h-3 text-[#64748B] dark:text-[#94A3B8]" />}
              <span>{copiedTopic ? 'Copied' : 'Copy'}</span>
            </button>

            <button
              onClick={() => (bookmarked ? removeBookmark(selectedNode.topic) : addBookmark(selectedNode.topic))}
              className="flex items-center gap-1 px-2 py-0.5 rounded bg-white dark:bg-[#1E293B] hover:bg-slate-100 dark:hover:bg-[#334155] text-[#0F172A] dark:text-[#E2E8F0] text-[10px] font-mono border border-[#CBD5E1] dark:border-[#334155] transition-colors cursor-pointer"
              title="Bookmark Topic"
            >
              {bookmarked ? (
                <Bookmark className="w-3 h-3 text-amber-600 dark:text-[#FFC107] fill-current" />
              ) : (
                <BookmarkPlus className="w-3 h-3 text-[#64748B] dark:text-[#94A3B8]" />
              )}
            </button>

            <button
              onClick={() => jumpToHistorian(selectedNode.topic)}
              className="flex items-center gap-1 px-2.5 py-0.5 rounded bg-amber-50 dark:bg-[#FFC107]/10 border border-amber-300 dark:border-[#FFC107]/40 hover:bg-amber-100 dark:hover:bg-[#FFC107]/20 text-amber-900 dark:text-[#FFC107] text-[10px] font-mono transition-colors cursor-pointer font-semibold"
              title="Open in Timescale Historian"
            >
              <History className="w-3 h-3 text-amber-600 dark:text-[#FFC107]" />
              <span>Historian</span>
            </button>
          </div>
        </div>

        {/* Node Metadata Strip */}
        <div className="flex flex-wrap items-center gap-3 text-[10px] font-mono text-[#475569] dark:text-[#94A3B8] pt-1">
          <div className="flex items-center gap-1">
            <Server className="w-3 h-3 text-[#64748B]" />
            <span>PUB:</span>
            <span className="text-[#0F172A] dark:text-[#F8FAFC] font-semibold">{selectedNode.publisher || '—'}</span>
          </div>

          <div className="flex items-center gap-1">
            <Clock className="w-3 h-3 text-[#64748B]" />
            <span>UPDATED:</span>
            <span className={stale ? 'text-amber-700 dark:text-[#FFC107] font-semibold' : 'text-emerald-700 dark:text-[#10B981] font-semibold'}>
              {new Date(selectedNode.lastUpdated).toLocaleTimeString()}
            </span>
          </div>

          <button
            onClick={() => setFeedTopicFilter(`${selectedNode.topic}/#`)}
            className="flex items-center gap-1 text-[#475569] dark:text-[#94A3B8] hover:text-amber-600 dark:hover:text-[#FFC107] ml-auto transition-colors cursor-pointer"
            title="Filter Live Feed to this topic subtree"
          >
            <Filter className="w-3 h-3" />
            <span>Filter Subtree</span>
          </button>
        </div>
      </div>

      {/* Main Content Area */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3 scrollbar-thin scrollbar-thumb-slate-300 dark:scrollbar-thumb-[#1E293B]">
        {/* Real-time Parameters Banner Grid */}
        {numericMetrics.length > 0 && (
          <div className="bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] rounded-lg p-3 space-y-2 shadow-xs">
            <div className="flex items-center justify-between text-[10px] text-[#64748B]">
              <span className="flex items-center gap-1.5 text-[#0F172A] dark:text-[#F8FAFC] font-serif font-bold text-xs">
                <Gauge className="w-3.5 h-3.5 text-amber-600 dark:text-[#FFC107]" />
                <span>Real-time Parameters</span>
              </span>
              <span className="text-emerald-700 dark:text-[#10B981] flex items-center gap-1 font-mono text-[9px] font-semibold tracking-wider">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 dark:bg-[#10B981] animate-pulse" />
                <span>LIVE TELEMETRY</span>
              </span>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {numericMetrics.slice(0, 6).map((m) => (
                <div
                  key={m.key}
                  className="bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#E2E8F0] dark:border-[#1E293B] rounded p-2 font-mono flex flex-col justify-between"
                >
                  <div className="text-[9px] text-[#64748B] dark:text-[#94A3B8] truncate uppercase font-semibold">{m.key}</div>
                  <div className="flex items-baseline gap-1 mt-1">
                    <span className="text-base font-bold text-amber-600 dark:text-[#FFC107] tracking-tight">
                      {typeof m.value === 'number' ? m.value.toFixed(1) : m.value}
                    </span>
                    {m.unit && <span className="text-[10px] text-[#64748B]">{m.unit}</span>}
                  </div>
                </div>
              ))}
            </div>

            {/* Output stability indicator */}
            <div className="pt-1 flex items-center justify-between text-[9px] font-mono text-[#64748B]">
              <span>OUTPUT STABILITY</span>
              <div className="flex gap-1">
                <div className="w-3 h-1.5 rounded-sm bg-emerald-500 dark:bg-[#10B981]" />
                <div className="w-3 h-1.5 rounded-sm bg-emerald-500 dark:bg-[#10B981]" />
                <div className="w-3 h-1.5 rounded-sm bg-emerald-500 dark:bg-[#10B981]" />
                <div className="w-3 h-1.5 rounded-sm bg-amber-500 dark:bg-[#FFC107]" />
                <div className="w-3 h-1.5 rounded-sm bg-slate-300 dark:bg-[#1E293B]" />
              </div>
            </div>
          </div>
        )}

        {/* Current Payload Viewer */}
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

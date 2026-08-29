import React, { useState, useRef, useEffect } from 'react';
import {
  Radio,
  Pause,
  Play,
  Trash2,
  Filter,
  ExternalLink,
  Lock,
  Unlock,
  Terminal,
} from 'lucide-react';
import { useUNS } from '../../context/UNSContext';
import { JsonViewer } from '../common/JsonViewer';

export const LiveMqttFeed: React.FC = () => {
  const {
    mqttFeed,
    isFeedPaused,
    setIsFeedPaused,
    feedTopicFilter,
    setFeedTopicFilter,
    clearMqttFeed,
    followSelection,
    setFollowSelection,
    selectedNode,
    jumpToTopicInTree,
    settings,
  } = useUNS();

  const [expandedMsgId, setExpandedMsgId] = useState<string | null>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const feedContainerRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to top when new messages arrive if enabled
  useEffect(() => {
    if (autoScroll && feedContainerRef.current) {
      feedContainerRef.current.scrollTop = 0;
    }
  }, [mqttFeed, autoScroll]);

  return (
    <div id="live-mqtt-feed-panel" className="flex flex-col h-full bg-white dark:bg-[#0B0B0C] w-full overflow-hidden">
      {/* Top Header & Controls */}
      <div className="p-2.5 border-b border-[#E2E8F0] dark:border-[#1E293B] bg-[#F8FAFC] dark:bg-[#111114] flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${isFeedPaused ? 'bg-[#64748B]' : 'bg-emerald-500 dark:bg-[#10B981] animate-pulse'}`} />
          <span className="font-serif font-bold text-[#0F172A] dark:text-[#F8FAFC] text-xs tracking-wide uppercase">
            Live MQTT Feed
          </span>
          <span className="px-1.5 py-0.2 rounded bg-slate-200 dark:bg-[#1E293B] text-[#475569] dark:text-[#94A3B8] font-mono text-[9px] font-semibold">
            {mqttFeed.length}/{settings.maxFeedBuffer}
          </span>
        </div>

        {/* Action buttons */}
        <div className="flex items-center gap-1">
          {/* Pause / Resume */}
          <button
            id="feed-pause-toggle-btn"
            onClick={() => setIsFeedPaused((prev) => !prev)}
            className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-medium transition-colors cursor-pointer ${
              isFeedPaused
                ? 'bg-amber-100 dark:bg-amber-500/10 border border-amber-300 dark:border-amber-500/40 text-amber-800 dark:text-[#FFC107] hover:bg-amber-200 dark:hover:bg-amber-500/20 font-semibold'
                : 'bg-white dark:bg-[#1E293B] hover:bg-slate-100 dark:hover:bg-[#334155] text-[#0F172A] dark:text-[#E2E8F0] border border-[#CBD5E1] dark:border-[#334155]'
            }`}
            title={isFeedPaused ? 'Resume live message stream' : 'Pause feed (drops incoming to save memory)'}
          >
            {isFeedPaused ? <Play className="w-2.5 h-2.5 fill-current" /> : <Pause className="w-2.5 h-2.5 fill-current" />}
            <span>{isFeedPaused ? 'Paused (Drops)' : 'Pause'}</span>
          </button>

          {/* Auto-scroll */}
          <button
            onClick={() => setAutoScroll(!autoScroll)}
            className={`p-1 rounded text-[10px] border border-[#CBD5E1] dark:border-[#334155] transition-colors cursor-pointer ${
              autoScroll ? 'bg-amber-50 dark:bg-[#1E293B] text-amber-700 dark:text-[#FFC107] font-semibold' : 'bg-white dark:bg-[#0B0B0C] text-[#64748B] hover:text-[#0F172A] dark:hover:text-[#E2E8F0]'
            }`}
            title={autoScroll ? 'Auto-scroll active' : 'Auto-scroll disabled'}
          >
            {autoScroll ? <Lock className="w-3 h-3" /> : <Unlock className="w-3 h-3" />}
          </button>

          {/* Clear */}
          <button
            onClick={clearMqttFeed}
            className="p-1 rounded bg-white dark:bg-[#1E293B] hover:bg-slate-100 dark:hover:bg-[#334155] border border-[#CBD5E1] dark:border-[#334155] text-[#64748B] hover:text-rose-600 dark:hover:text-rose-400 transition-colors cursor-pointer"
            title="Clear message buffer"
          >
            <Trash2 className="w-3 h-3" />
          </button>
        </div>
      </div>

      {/* Feed Messages List */}
      <div
        ref={feedContainerRef}
        id="mqtt-feed-list"
        className="flex-1 overflow-y-auto p-2 space-y-1.5 scrollbar-thin scrollbar-thumb-slate-300 dark:scrollbar-thumb-[#1E293B] bg-slate-50 dark:bg-[#0B0B0C]"
      >
        {mqttFeed.length === 0 ? (
          <div className="text-center py-12 text-[#64748B] text-xs font-mono">
            <Radio className="w-6 h-6 mx-auto mb-2 text-[#94A3B8] dark:text-[#475569] animate-pulse" />
            <p>Waiting for MQTT messages...</p>
            <p className="text-[9px] mt-1 text-[#64748B]">
              Subscribed:{' '}
              {followSelection && selectedNode
                ? `${selectedNode.topic}/#`
                : feedTopicFilter || '#'}
            </p>
          </div>
        ) : (
          mqttFeed.map((msg) => {
            const isSpb = msg.topic.startsWith('spBv1.0/') || msg.isSparkplug;
            const isExpanded = expandedMsgId === msg.id;
            const timeStr = new Date(msg.timestamp).toLocaleTimeString();

            // Distinct left border color based on topic type
            let borderColor = 'border-l-blue-500'; // default blue
            if (isSpb) borderColor = 'border-l-emerald-500 dark:border-l-[#10B981]'; // Sparkplug B emerald
            else if (msg.topic.toLowerCase().includes('alarm') || msg.topic.toLowerCase().includes('event')) {
              borderColor = 'border-l-amber-500 dark:border-l-[#FFC107]'; // amber
            }

            return (
              <div
                key={msg.id}
                id={`mqtt-msg-${msg.id}`}
                onClick={() => setExpandedMsgId(isExpanded ? null : msg.id)}
                className={`p-2 rounded bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] border-l-3 ${borderColor} text-[10px] font-mono cursor-pointer transition-all hover:bg-slate-100/70 dark:hover:bg-[#1E293B]/40 shadow-2xs ${
                  isExpanded ? 'shadow-md border-slate-400 dark:border-[#334155]' : ''
                }`}
              >
                {/* Message Header */}
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[9px] text-[#64748B] font-medium">{timeStr}</span>

                  <div className="flex items-center gap-1">
                    {/* Sparkplug B Badge */}
                    {isSpb && (
                      <span className="px-1 py-0 rounded bg-purple-100 dark:bg-[#1E293B] border border-purple-300 dark:border-[#A855F7]/50 text-purple-700 dark:text-[#A855F7] text-[8px] font-bold">
                        SPB
                      </span>
                    )}

                    {msg.publisher && (
                      <span className="text-[8px] text-[#475569] dark:text-[#94A3B8] bg-slate-100 dark:bg-[#0B0B0C] px-1 py-0 rounded border border-[#E2E8F0] dark:border-[#1E293B]">
                        {msg.publisher.split(':').pop()}
                      </span>
                    )}
                  </div>
                </div>

                {/* Topic Path */}
                <div className="text-[10px] text-[#0F172A] dark:text-[#F8FAFC] break-all font-semibold mb-1">
                  {msg.topic}
                </div>

                {/* Payload summary or Expanded Viewer */}
                {!isExpanded ? (
                  <div className="text-[9px] text-[#475569] dark:text-[#94A3B8] truncate bg-slate-100 dark:bg-[#0B0B0C] rounded px-1.5 py-0.5 border border-[#E2E8F0] dark:border-[#1E293B]">
                    {typeof msg.payload === 'object' && msg.payload !== null
                      ? JSON.stringify(msg.payload)
                      : String(msg.payload || msg.rawPayload || '')}
                  </div>
                ) : (
                  <div className="mt-2 pt-2 border-t border-[#E2E8F0] dark:border-[#1E293B] space-y-2">
                    <JsonViewer data={msg.payload} title="MESSAGE PAYLOAD" maxHeight="max-h-56" />

                    <div className="flex items-center justify-between pt-1">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          jumpToTopicInTree(msg.topic);
                        }}
                        className="flex items-center gap-1 text-[10px] text-amber-700 dark:text-[#FFC107] hover:underline font-semibold"
                      >
                        <ExternalLink className="w-3 h-3" />
                        <span>Locate in Hierarchy</span>
                      </button>

                      <span className="text-[9px] text-[#64748B]">ID: {msg.id}</span>
                    </div>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* Bottom Command / Topic Subscription Bar */}
      <div className="p-2 border-t border-[#E2E8F0] dark:border-[#1E293B] bg-[#F8FAFC] dark:bg-[#111114] space-y-1.5 shrink-0">
        <div className="bg-white dark:bg-[#0B0B0C] border border-[#CBD5E1] dark:border-[#1E293B] rounded px-2 py-1 flex items-center gap-2">
          <Terminal className="w-3 h-3 text-[#64748B] shrink-0" />
          <span className="text-emerald-600 dark:text-[#10B981] font-mono text-[10px] font-bold">$</span>
          <input
            type="text"
            value={feedTopicFilter}
            onChange={(e) => setFeedTopicFilter(e.target.value)}
            disabled={followSelection}
            placeholder="Subscribe topic (# or CovestroAG/#)"
            className="w-full bg-transparent text-[10px] text-[#0F172A] dark:text-[#F8FAFC] font-mono focus:outline-none placeholder-[#64748B]"
          />
        </div>

        {/* Follow Selection Toggle */}
        <div className="flex items-center justify-between text-[9px] font-mono text-[#64748B] px-1">
          <label className="flex items-center gap-1.5 cursor-pointer hover:text-[#0F172A] dark:hover:text-[#94A3B8] select-none">
            <input
              type="checkbox"
              checked={followSelection}
              onChange={(e) => setFollowSelection(e.target.checked)}
              className="rounded border-[#CBD5E1] dark:border-[#334155] bg-white dark:bg-[#0B0B0C] text-amber-500 dark:text-[#FFC107] focus:ring-0 w-3 h-3"
            />
            <span>Follow selected node ({selectedNode ? selectedNode.name : 'none'})</span>
          </label>
        </div>
      </div>
    </div>
  );
};

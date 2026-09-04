import React, { useState, useRef, useEffect } from 'react';
import {
  Radio,
  Trash2,
  Terminal,
} from 'lucide-react';
import { useUNS } from '../../context/UNSContext';
import { JsonViewer } from '../common/JsonViewer';
import { consoleTokens } from '../ui/console-ui';

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
    <div id="live-mqtt-feed-panel" className={`${consoleTokens.pane} w-full overflow-hidden`}>
      <div className={`${consoleTokens.paneHeader} flex items-center justify-between`}>
        <div className="flex items-center gap-2">
          <span className={`size-2 rounded-full ${isFeedPaused ? 'bg-zinc-600' : 'bg-emerald-500 animate-pulse'}`} />
          <span className="text-sm font-semibold text-white">Live Feed</span>
          <span className="rounded-md bg-zinc-800 px-1.5 py-0.5 text-[10px] tabular-nums text-zinc-400">
            {mqttFeed.length}/{settings.maxFeedBuffer}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button
            id="feed-pause-toggle-btn"
            onClick={() => setIsFeedPaused((prev) => !prev)}
            className="rounded-lg px-2 py-1 text-xs text-zinc-400 hover:bg-zinc-800 hover:text-[#FF7A00]"
          >
            {isFeedPaused ? 'Resume' : 'Pause'}
          </button>
          <button onClick={clearMqttFeed} className="rounded-lg p-1.5 text-zinc-500 hover:bg-zinc-800 hover:text-red-400" title="Clear feed">
            <Trash2 className="size-3.5" />
          </button>
        </div>
      </div>

      <div ref={feedContainerRef} id="mqtt-feed-list" className="flex-1 space-y-2 overflow-y-auto p-2">
        {mqttFeed.length === 0 ? (
          <div className="py-12 text-center text-sm text-zinc-600">
            <Radio className="mx-auto mb-2 size-6 animate-pulse text-zinc-700" />
            <p>Waiting for MQTT messages…</p>
          </div>
        ) : (
          mqttFeed.map((msg) => {
            const isExpanded = expandedMsgId === msg.id;
            const timeStr = new Date(msg.timestamp).toLocaleTimeString();

            return (
              <div
                key={msg.id}
                onClick={() => setExpandedMsgId(isExpanded ? null : msg.id)}
                className="cursor-pointer rounded-xl border border-zinc-800 bg-zinc-900/40 p-2.5 transition-colors hover:border-zinc-700"
              >
                <div className="mb-1 flex items-center justify-between text-xs text-zinc-500">
                  <span>{timeStr}</span>
                  {msg.publisher && <span>{msg.publisher.split(':').pop()}</span>}
                </div>
                <div className="mb-1 truncate text-sm text-[#FF7A00]">{msg.topic}</div>
                {!isExpanded ? (
                  <div className="truncate text-xs text-zinc-500">
                    {typeof msg.payload === 'object' && msg.payload !== null
                      ? JSON.stringify(msg.payload)
                      : String(msg.payload || msg.rawPayload || '')}
                  </div>
                ) : (
                  <div className="mt-2 border-t border-zinc-800 pt-2">
                    <JsonViewer data={msg.payload} title="Payload" maxHeight="max-h-56" />
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      <div className="shrink-0 space-y-2 border-t border-zinc-800 p-2">
        <div className="flex items-center gap-2">
          <Terminal className="size-3.5 shrink-0 text-[#FF7A00]" />
          <input
            type="text"
            value={feedTopicFilter}
            onChange={(e) => setFeedTopicFilter(e.target.value)}
            placeholder={`# or ${settings.organization}/#`}
            className={`${consoleTokens.inputOrange} flex-1 py-1.5 text-xs`}
          />
        </div>
        <label className="flex items-center gap-2 text-xs text-zinc-500">
          <input
            type="checkbox"
            checked={followSelection}
            onChange={(e) => setFollowSelection(e.target.checked)}
            className="accent-[#FF7A00]"
          />
          Follow selected node {selectedNode ? `(${selectedNode.name})` : ''}
        </label>
      </div>
    </div>
  );
};

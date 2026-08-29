import React, { useState, useEffect, useRef } from 'react';
import {
  Workflow,
  Radio,
  Pause,
  Play,
  Trash2,
  AlertTriangle,
  Lock,
  Unlock,
  FileCode,
  Layers,
  ChevronRight,
} from 'lucide-react';
import { KafkaMessage } from '../../types/uns';
import { unsGraphQLClient } from '../../services/graphql/client';
import { JsonViewer } from '../common/JsonViewer';
import { useUNS } from '../../context/UNSContext';

export const KafkaStreamsView: React.FC = () => {
  const { kafkaInitialTopic } = useUNS();

  const [topicInput, setTopicInput] = useState(
    kafkaInitialTopic || 'uns.telemetry.raw, uns.events.normalized'
  );
  const [activeTopics, setActiveTopics] = useState<string[]>([]);
  const [wildcardError, setWildcardError] = useState<string | null>(null);

  const [messages, setMessages] = useState<KafkaMessage[]>([]);
  const [isPaused, setIsPaused] = useState<boolean>(false);
  const [bufferSize] = useState<number>(300);
  const [autoScroll, setAutoScroll] = useState<boolean>(true);
  const [selectedMessage, setSelectedMessage] = useState<KafkaMessage | null>(null);
  const [mobileTab, setMobileTab] = useState<'stream' | 'detail'>('stream');

  // Rate tracking
  const [msgRate, setMsgRate] = useState<number>(0);
  const messageCountRef = useRef<number>(0);
  const isPausedRef = useRef<boolean>(isPaused);
  isPausedRef.current = isPaused;

  const containerRef = useRef<HTMLDivElement>(null);

  // Validate topics (strictly no # or + wildcards allowed for Kafka)
  const validateAndSubscribe = (raw: string) => {
    if (raw.includes('#') || raw.includes('+') || raw.includes('*')) {
      setWildcardError('Kafka topics cannot contain wildcards (#, +, *). Please enter exact topic names.');
      return;
    }

    setWildcardError(null);
    const topics = raw
      .split(',')
      .map((t) => t.trim())
      .filter((t) => t.length > 0);

    setActiveTopics(topics);
  };

  // Subscribe to Kafka topics
  useEffect(() => {
    if (activeTopics.length === 0) return;

    const unsubscribe = unsGraphQLClient.subscribeKafkaMessages(activeTopics, (msg) => {
      if (isPausedRef.current) return;

      messageCountRef.current += 1;
      setMessages((prev) => {
        const next = [msg, ...prev];
        return next.length > bufferSize ? next.slice(0, bufferSize) : next;
      });

      if (autoScroll && containerRef.current) {
        containerRef.current.scrollTop = 0;
      }
    });

    return () => {
      unsubscribe();
    };
  }, [activeTopics, bufferSize, autoScroll]);

  // Rate calculation loop
  useEffect(() => {
    const interval = setInterval(() => {
      setMsgRate(messageCountRef.current);
      messageCountRef.current = 0;
    }, 1000);

    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (kafkaInitialTopic) {
      setTopicInput(kafkaInitialTopic);
      validateAndSubscribe(kafkaInitialTopic);
    }
  }, [kafkaInitialTopic]);

  const handleSelectMessage = (msg: KafkaMessage) => {
    setSelectedMessage(msg);
  };

  return (
    <div id="kafka-streams-view" className="flex-1 flex flex-col h-full bg-[#050505] text-[#F8FAFC] font-mono text-xs overflow-hidden">
      {/* Mobile / Tablet Tab Switcher on < lg */}
      <div className="lg:hidden bg-[#111114] border-b border-[#1E293B] p-2.5 shrink-0">
        <div className="flex items-center bg-[#0B0B0C] p-1 rounded-lg border border-[#1E293B] gap-1">
          <button
            onClick={() => setMobileTab('stream')}
            className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-md text-xs font-mono transition-all cursor-pointer ${
              mobileTab === 'stream'
                ? 'bg-[#FFC107] text-[#0B0B0C] font-bold shadow-sm'
                : 'text-[#94A3B8] hover:text-[#F8FAFC]'
            }`}
          >
            <Workflow className="w-3.5 h-3.5" />
            <span>Messages ({messages.length})</span>
          </button>
          <button
            onClick={() => setMobileTab('detail')}
            className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-md text-xs font-mono transition-all cursor-pointer ${
              mobileTab === 'detail'
                ? 'bg-[#FFC107] text-[#0B0B0C] font-bold shadow-sm'
                : 'text-[#94A3B8] hover:text-[#F8FAFC]'
            }`}
          >
            <FileCode className="w-3.5 h-3.5" />
            <span>Detail {selectedMessage ? '✓' : ''}</span>
          </button>
        </div>
      </div>

      <div className="flex-1 grid grid-cols-1 lg:grid-cols-12 h-full overflow-hidden">
        {/* Left Column: Streams Feed (7 cols on lg) */}
        <div className={`lg:col-span-7 flex flex-col h-full border-r border-[#1E293B] bg-[#111114] overflow-hidden ${
          mobileTab === 'detail' ? 'hidden lg:flex' : 'flex'
        }`}>
          {/* Controls Bar */}
          <div className="p-3 bg-[#111114] border-b border-[#1E293B] space-y-2.5 shrink-0">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <div className="w-7 h-7 rounded bg-[#0B0B0C] border border-[#1E293B] flex items-center justify-center text-[#FFC107]">
                  <Workflow className="w-4 h-4" />
                </div>
                <div>
                  <h2 className="font-bold text-[#F8FAFC] text-xs uppercase tracking-wider">Kafka Stream Monitor</h2>
                  <div className="flex items-center gap-2 text-[10px] text-[#64748B]">
                    <span>Throughput: <b className="text-[#10B981]">{msgRate} msg/s</b></span>
                    <span>•</span>
                    <span>Buffer: <b className="text-[#F8FAFC]">{messages.length}/{bufferSize}</b></span>
                  </div>
                </div>
              </div>

              {/* Stream Action Buttons */}
              <div className="flex items-center gap-1.5">
                <button
                  onClick={() => setIsPaused(!isPaused)}
                  className={`flex items-center gap-1 px-2.5 py-1 rounded text-[10px] font-mono font-medium transition-colors cursor-pointer ${
                    isPaused
                      ? 'bg-amber-600/20 border border-amber-500/40 text-amber-300'
                      : 'bg-[#0B0B0C] border border-[#1E293B] hover:bg-[#1E293B] text-[#94A3B8]'
                  }`}
                >
                  {isPaused ? <Play className="w-3 h-3 fill-current" /> : <Pause className="w-3 h-3 fill-current" />}
                  <span>{isPaused ? 'Paused' : 'Pause'}</span>
                </button>

                <button
                  onClick={() => setAutoScroll(!autoScroll)}
                  className={`p-1.5 rounded border border-[#1E293B] transition-colors cursor-pointer ${
                    autoScroll ? 'bg-[#0B0B0C] text-[#FFC107]' : 'bg-[#0B0B0C] text-[#64748B] hover:text-[#94A3B8]'
                  }`}
                  title="Toggle Auto-Scroll"
                >
                  {autoScroll ? <Lock className="w-3.5 h-3.5" /> : <Unlock className="w-3.5 h-3.5" />}
                </button>

                <button
                  onClick={() => setMessages([])}
                  className="p-1.5 rounded bg-[#0B0B0C] border border-[#1E293B] hover:bg-[#1E293B] text-[#64748B] hover:text-rose-400 transition-colors cursor-pointer"
                  title="Clear Ring Buffer"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>

            {/* Topic Subscription Input */}
            <div className="space-y-1.5">
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={topicInput}
                  onChange={(e) => setTopicInput(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && validateAndSubscribe(topicInput)}
                  placeholder="Enter exact Kafka topics (comma-separated, no wildcards)..."
                  className="flex-1 bg-[#0B0B0C] border border-[#1E293B] rounded px-2.5 py-1.5 text-[11px] text-[#F8FAFC] focus:outline-none focus:border-[#FFC107] font-mono min-w-0"
                />
                <button
                  onClick={() => validateAndSubscribe(topicInput)}
                  className="px-3 py-1.5 bg-[#FFC107] hover:bg-[#FFB300] text-[#0B0B0C] font-bold rounded transition-colors font-mono text-xs cursor-pointer shrink-0"
                >
                  Subscribe
                </button>
              </div>

              {wildcardError && (
                <div className="p-2 rounded bg-rose-950/40 border border-rose-800 text-rose-300 text-[10px] flex items-center gap-1.5">
                  <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                  <span>{wildcardError}</span>
                </div>
              )}
            </div>
          </div>

          {/* Message Stream Table / List */}
          <div
            ref={containerRef}
            className="flex-1 overflow-y-auto p-3 space-y-1.5 scrollbar-thin scrollbar-thumb-[#1E293B]"
          >
            {activeTopics.length === 0 ? (
              <div className="text-center py-16 text-[#64748B]">
                <Workflow className="w-10 h-10 mx-auto mb-3 text-[#64748B]" />
                <h3 className="text-[#94A3B8] font-semibold">Enter a Kafka topic (no wildcards).</h3>
                <p className="text-[10px] mt-1 text-[#64748B]">
                  e.g. <code className="text-[#FFC107]">uns.telemetry.raw</code>, <code className="text-[#FFC107]">uns.events.normalized</code>
                </p>
              </div>
            ) : messages.length === 0 ? (
              <div className="text-center py-16 text-[#64748B]">
                <Radio className="w-8 h-8 mx-auto mb-2 text-[#64748B] animate-pulse" />
                <p>Listening for Kafka events on {activeTopics.join(', ')}...</p>
              </div>
            ) : (
              messages.map((msg) => {
                const isSelected = selectedMessage?.id === msg.id;

                return (
                  <div
                    key={msg.id}
                    onClick={() => {
                      handleSelectMessage(msg);
                      if (window.innerWidth < 1024) {
                        setMobileTab('detail');
                      }
                    }}
                    className={`p-2.5 rounded border text-xs cursor-pointer transition-all ${
                      isSelected
                        ? 'bg-[#1E293B] border-[#FFC107] shadow-lg'
                        : 'bg-[#0B0B0C] border-[#1E293B] hover:bg-[#111114] hover:border-[#334155]'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <div className="flex items-center gap-2">
                        <span className="px-1.5 py-0.2 rounded bg-[#111114] border border-[#1E293B] text-[#FFC107] text-[10px] font-bold">
                          {msg.topic}
                        </span>
                        {msg.partition !== undefined && (
                          <span className="text-[9px] text-[#64748B]">
                            Part: {msg.partition} • Off: {msg.offset}
                          </span>
                        )}
                      </div>
                      <span className="text-[9px] text-[#64748B]">
                        {new Date(msg.timestamp).toLocaleTimeString()}
                      </span>
                    </div>

                    <div className="font-mono text-[10px] text-[#94A3B8] truncate bg-[#050505] rounded px-1.5 py-0.5 border border-[#1E293B]">
                      {typeof msg.payload === 'object' && msg.payload !== null
                        ? JSON.stringify(msg.payload)
                        : String(msg.payload || msg.rawPayload || '')}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Right Column: Message Detail Inspector (5 cols on lg) */}
        <div className={`lg:col-span-5 flex flex-col h-full bg-[#0B0B0C] overflow-hidden p-4 space-y-4 ${
          mobileTab === 'stream' ? 'hidden lg:flex' : 'flex'
        }`}>
          <div className="pb-2 border-b border-[#1E293B] flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="font-bold text-[#F8FAFC] text-xs uppercase tracking-wider">Kafka Message Detail</span>
              {selectedMessage && (
                <span className="px-1.5 py-0.2 rounded bg-[#1E293B] text-[#FFC107] text-[9px] font-mono">
                  {selectedMessage.topic}
                </span>
              )}
            </div>
            {selectedMessage && (
              <span className="text-[9px] text-[#64748B] font-mono">ID: {selectedMessage.id}</span>
            )}
          </div>

          {selectedMessage ? (
            <div className="flex-1 overflow-y-auto space-y-3 scrollbar-thin scrollbar-thumb-[#1E293B]">
              {/* Metadata Card */}
              <div className="p-3 rounded bg-[#111114] border border-[#1E293B] space-y-1.5 text-[10px]">
                <div className="flex justify-between">
                  <span className="text-[#64748B]">Topic:</span>
                  <span className="text-[#FFC107] font-semibold">{selectedMessage.topic}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[#64748B]">Timestamp:</span>
                  <span className="text-[#F8FAFC]">{selectedMessage.timestamp}</span>
                </div>
                {selectedMessage.key && (
                  <div className="flex justify-between">
                    <span className="text-[#64748B]">Message Key:</span>
                    <span className="text-emerald-400 font-bold">{selectedMessage.key}</span>
                  </div>
                )}
                <div className="flex justify-between">
                  <span className="text-[#64748B]">Partition / Offset:</span>
                  <span className="text-[#94A3B8]">
                    {selectedMessage.partition ?? 0} / {selectedMessage.offset ?? 0}
                  </span>
                </div>
              </div>

              {/* JSON Payload Viewer */}
              <div className="space-y-1.5">
                <span className="text-[10px] text-[#94A3B8] font-bold uppercase tracking-wider">Payload:</span>
                <div className="bg-[#111114] border border-[#1E293B] rounded-lg p-3 overflow-x-auto">
                  <JsonViewer data={selectedMessage.payload} />
                </div>
              </div>

              {/* Headers if present */}
              {selectedMessage.headers && Object.keys(selectedMessage.headers).length > 0 && (
                <div className="space-y-1.5">
                  <span className="text-[10px] text-[#94A3B8] font-bold uppercase tracking-wider">Kafka Headers:</span>
                  <div className="bg-[#111114] border border-[#1E293B] rounded-lg p-3 text-[10px]">
                    <table className="w-full">
                      <tbody>
                        {Object.entries(selectedMessage.headers).map(([k, v]) => (
                          <tr key={k} className="border-b border-[#1E293B]/50 last:border-0">
                            <td className="text-[#64748B] py-1 font-mono">{k}</td>
                            <td className="text-[#F8FAFC] py-1 font-mono text-right">{v}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center text-center p-6 text-[#64748B]">
              <Workflow className="w-10 h-10 mb-2 opacity-40 text-[#FFC107]" />
              <p className="text-xs text-[#94A3B8]">Select a Kafka message from the stream to inspect payload &amp; headers.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

import React, { useState, useEffect, useCallback } from 'react';
import {
  Search,
  Calendar,
  Clock,
  Filter,
  Layers,
  Database,
  Tag,
  Server,
  RefreshCw,
  Sliders,
  AlertCircle,
} from 'lucide-react';
import { useUNS } from '../../context/UNSContext';
import { HistoricEvent, UnsNode, BinaryOperator } from '../../types/uns';
import { HistorianTable } from './HistorianTable';
import { unsGraphQLClient } from '../../services/graphql/client';
import { historianTopic } from '../../lib/uns/topics';
import { useTheme } from '../../context/ThemeContext';
import {
  GRAFANA_DASHBOARDS,
  GrafanaEmbed,
  grafanaRangeFromPreset,
  grafanaTopicFilter,
} from '../common/GrafanaEmbed';
import {
  PageShell,
  PageContent,
  ConsoleCard,
  SegmentTabs,
  ConsoleInput,
  ConsoleSelect,
  BtnPrimary,
  consoleTokens,
} from '../ui/console-ui';

type QueryMode = 'topic_time' | 'publishers' | 'property_event' | 'property_nodes';
type TimePreset = '5m' | '15m' | '1h' | '6h' | '24h' | 'all' | 'custom';

export const ExploreView: React.FC = () => {
  const { historianInitialTopic, allLoadedNodes, selectedNode } = useUNS();
  const { isDark } = useTheme();

  const [mode, setMode] = useState<QueryMode>('topic_time');
  const [topicInput, setTopicInput] = useState(
    historianInitialTopic || selectedNode?.topic || ''
  );

  // Time range presets
  const [timePreset, setTimePreset] = useState<TimePreset>('1h');
  const [customStartTime, setCustomStartTime] = useState(() => new Date(Date.now() - 3600 * 1000).toISOString().slice(0, 16));
  const [customEndTime, setCustomEndTime] = useState(() => new Date().toISOString().slice(0, 16));

  // Publisher filter
  const [publishersInput, setPublishersInput] = useState('');

  // Property query
  const [propKeysInput, setPropKeysInput] = useState('site');
  const [propOperator, setPropOperator] = useState<BinaryOperator>('OR');
  const [excludeTopicsInput, setExcludeTopicsInput] = useState('spBv1.0/#');

  // Results
  const [events, setEvents] = useState<HistoricEvent[]>([]);
  const [matchingNodes, setMatchingNodes] = useState<UnsNode[]>([]);
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Calculate start & end ISO strings based on preset
  const getTimeBounds = useCallback((): { start?: string; end?: string } => {
    if (timePreset === 'all') return {};
    const now = Date.now();
    if (timePreset === '5m') return { start: new Date(now - 5 * 60 * 1000).toISOString(), end: new Date(now).toISOString() };
    if (timePreset === '15m') return { start: new Date(now - 15 * 60 * 1000).toISOString(), end: new Date(now).toISOString() };
    if (timePreset === '1h') return { start: new Date(now - 60 * 60 * 1000).toISOString(), end: new Date(now).toISOString() };
    if (timePreset === '6h') return { start: new Date(now - 6 * 3600 * 1000).toISOString(), end: new Date(now).toISOString() };
    if (timePreset === '24h') return { start: new Date(now - 24 * 3600 * 1000).toISOString(), end: new Date(now).toISOString() };
    return { start: new Date(customStartTime).toISOString(), end: new Date(customEndTime).toISOString() };
  }, [timePreset, customStartTime, customEndTime]);

  const resolveHistorianTopic = (topic: string): string => {
    const trimmed = topic.trim();
    if (!trimmed || trimmed.includes('#') || trimmed.includes('+')) {
      return trimmed;
    }
    return historianTopic(trimmed);
  };

  // Execute Query
  const runQuery = useCallback(async () => {
    setLoading(true);
    setErrorMsg(null);
    try {
      const { start, end } = getTimeBounds();

      if (mode === 'topic_time') {
        if (!topicInput.trim()) {
          setErrorMsg('Enter a UNS topic (e.g. CovestroAG/Krefeld/.../G1). A /# suffix is added automatically.');
          setEvents([]);
          return;
        }
        const res = await unsGraphQLClient.getHistoricEvents(
          resolveHistorianTopic(topicInput),
          start,
          end,
        );
        setEvents(res);
      } else if (mode === 'publishers') {
        const pubList = publishersInput
          .split(',')
          .map((p) => p.trim())
          .filter((p) => p.length > 0);
        const res = await unsGraphQLClient.getHistoricEventsByPublishers(pubList, undefined, start, end);
        setEvents(res);
      } else if (mode === 'property_event') {
        const propertyKeys = propKeysInput
          .split(',')
          .map((key) => key.trim())
          .filter(Boolean);
        const res = await unsGraphQLClient.getHistoricEventsByProperty(propertyKeys, propOperator, undefined, start, end);
        setEvents(res);
      } else if (mode === 'property_nodes') {
        const propertyKeys = propKeysInput
          .split(',')
          .map((key) => key.trim())
          .filter(Boolean);
        const excludeTopics = excludeTopicsInput
          .split(',')
          .map((t) => t.trim())
          .filter(Boolean);
        const res = await unsGraphQLClient.getUnsNodesByProperty(
          propertyKeys,
          excludeTopics.length ? excludeTopics : undefined,
          excludeTopics.length > 0,
        );
        setMatchingNodes(res);
        setEvents(
          res.map((n) => ({
            id: `node_${n.topic}`,
            topic: n.topic,
            payload: n.payload || {},
            timestamp: n.lastUpdated,
            publisher: n.publisher,
          }))
        );
      }
    } catch (e: unknown) {
      setErrorMsg((e as Error).message || 'Failed to query historical events');
    } finally {
      setLoading(false);
    }
  }, [mode, topicInput, publishersInput, propKeysInput, propOperator, excludeTopicsInput, getTimeBounds]);

  // Run query on initial mount or when initial topic changes
  useEffect(() => {
    if (historianInitialTopic) {
      setTopicInput(historianInitialTopic);
    }
  }, [historianInitialTopic]);

  useEffect(() => {
    runQuery();
  }, [runQuery]);

  const grafanaTime =
    timePreset === 'custom'
      ? {
          from: String(new Date(customStartTime).getTime()),
          to: String(new Date(customEndTime).getTime()),
        }
      : grafanaRangeFromPreset(timePreset);
  const grafanaTopic = grafanaTopicFilter(topicInput) || 'CovestroAG';

  const modeTabs = [
    { id: 'topic_time', label: 'By Topic' },
    { id: 'publishers', label: 'By Publisher' },
    { id: 'property_event', label: 'By Property' },
    { id: 'property_nodes', label: 'Nodes by Property' },
  ];

  return (
    <PageShell id="explore-historian-view">
      <PageContent className="space-y-4">
      <ConsoleCard className="space-y-4">
        <div className="flex flex-col gap-4 border-b border-zinc-800 pb-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-3">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-[#FF7A00]/15">
              <Database className="size-5 text-[#FF7A00]" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-white">Historian Explorer</h2>
              <p className="text-sm text-zinc-500">Query historic events from TimescaleDB</p>
            </div>
          </div>
          <SegmentTabs
            tabs={modeTabs}
            active={mode}
            onChange={(id) => setMode(id as QueryMode)}
          />
        </div>

        {/* Dynamic Form Inputs according to Mode */}
        <div className="grid grid-cols-1 md:grid-cols-12 gap-3 items-end">
          {/* Mode 1: Topic + Time */}
          {mode === 'topic_time' && (
            <div className="md:col-span-6 space-y-1">
              <label className="text-[#64748B] dark:text-[#94A3B8] text-[10px] flex items-center gap-1">
                <Layers className="w-3 h-3 text-amber-600 dark:text-[#FFC107]" />
                <span>UNS TOPIC:</span>
              </label>
              <input
                type="text"
                value={topicInput}
                onChange={(e) => setTopicInput(e.target.value)}
                placeholder="e.g. CovestroAG/Dormagen/.../telemetry"
                className={consoleTokens.input}
              />
            </div>
          )}

          {/* Mode 2: Publisher Filter */}
          {mode === 'publishers' && (
            <div className="md:col-span-6 space-y-1">
              <label className="text-[#94A3B8] text-[10px] flex items-center gap-1">
                <Server className="w-3 h-3 text-[#FFC107]" />
                <span>PUBLISHERS (COMMA-SEPARATED):</span>
              </label>
              <input
                type="text"
                value={publishersInput}
                onChange={(e) => setPublishersInput(e.target.value)}
                placeholder="edge:siemens_s7_1500, edge:beckhoff_twincat"
                className={consoleTokens.input}
              />
            </div>
          )}

          {/* Mode 3: Property + Operator Filter */}
          {mode === 'property_event' && (
            <>
              <div className="md:col-span-4 space-y-1">
                <label className="text-[#94A3B8] text-[10px]">PROPERTY KEYS (comma-separated):</label>
                <input
                  type="text"
                  value={propKeysInput}
                  onChange={(e) => setPropKeysInput(e.target.value)}
                  placeholder="site, cell_id"
                  className={consoleTokens.input}
                />
              </div>
              <div className="md:col-span-2 space-y-1">
                <label className="text-[#94A3B8] text-[10px]">OPERATOR:</label>
                <select
                  value={propOperator}
                  onChange={(e) => setPropOperator(e.target.value as BinaryOperator)}
                  className={consoleTokens.input}
                >
                  <option value="OR">OR</option>
                  <option value="AND">AND</option>
                  <option value="NOT">NOT</option>
                </select>
              </div>
            </>
          )}

          {mode === 'property_nodes' && (
            <>
              <div className="md:col-span-4 space-y-1">
                <label className="text-[#94A3B8] text-[10px]">PROPERTY KEYS (comma-separated):</label>
                <input
                  type="text"
                  value={propKeysInput}
                  onChange={(e) => setPropKeysInput(e.target.value)}
                  placeholder="site, standard"
                  className={consoleTokens.input}
                />
              </div>
              <div className="md:col-span-4 space-y-1">
                <label className="text-[#94A3B8] text-[10px]">EXCLUDE TOPICS (comma-separated):</label>
                <input
                  type="text"
                  value={excludeTopicsInput}
                  onChange={(e) => setExcludeTopicsInput(e.target.value)}
                  placeholder="spBv1.0/#"
                  className={consoleTokens.input}
                />
              </div>
            </>
          )}

          {/* Time Range Selector (for time-based queries) */}
          {mode !== 'property_nodes' && (
            <div className="md:col-span-4 space-y-1">
              <label className="text-[#64748B] dark:text-[#94A3B8] text-[10px] flex items-center gap-1">
                <Clock className="w-3 h-3 text-amber-600 dark:text-[#FFC107]" />
                <span>TIME RANGE:</span>
              </label>
              <div className="flex items-center gap-1 bg-[#F1F5F9] dark:bg-[#0B0B0C] p-0.5 rounded border border-[#E2E8F0] dark:border-[#1E293B]">
                {(['5m', '15m', '1h', '6h', '24h', 'all', 'custom'] as const).map((p) => (
                  <button
                    key={p}
                    onClick={() => setTimePreset(p)}
                    className={`flex-1 py-1 rounded text-[10px] font-mono transition-colors cursor-pointer ${
                      timePreset === p ? 'bg-amber-500 dark:bg-[#FFC107] text-[#0B0B0C] font-bold' : 'text-[#64748B] dark:text-[#94A3B8] hover:text-[#0F172A] dark:hover:text-[#F8FAFC]'
                    }`}
                  >
                    {p}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Execute Query Button */}
          <div className="md:col-span-2">
            <BtnPrimary id="execute-graphql-historian-query-btn" onClick={runQuery} disabled={loading} className="w-full justify-center">
              <RefreshCw className={`size-4 ${loading ? 'animate-spin' : ''}`} />
              <span>{loading ? 'Querying...' : 'Run Query'}</span>
            </BtnPrimary>
          </div>
        </div>

        {/* Custom Date Picker row if custom selected */}
        {timePreset === 'custom' && mode !== 'property_nodes' && (
          <div className="flex flex-wrap items-center gap-3 pt-2 border-t border-[#E2E8F0] dark:border-[#1E293B] text-[10px]">
            <div className="flex items-center gap-1.5">
              <span className="text-[#64748B] dark:text-[#94A3B8]">Start ISO:</span>
              <input
                type="datetime-local"
                value={customStartTime}
                onChange={(e) => setCustomStartTime(e.target.value)}
                className="bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#CBD5E1] dark:border-[#1E293B] rounded px-2 py-0.5 text-[#0F172A] dark:text-[#F8FAFC] font-mono text-[10px]"
              />
            </div>
            <div className="flex items-center gap-1.5">
              <span className="text-[#64748B] dark:text-[#94A3B8]">End ISO:</span>
              <input
                type="datetime-local"
                value={customEndTime}
                onChange={(e) => setCustomEndTime(e.target.value)}
                className="bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#CBD5E1] dark:border-[#1E293B] rounded px-2 py-0.5 text-[#0F172A] dark:text-[#F8FAFC] font-mono text-[10px]"
              />
            </div>
          </div>
        )}

        {errorMsg && (
          <div className="flex items-center gap-2 rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
            <AlertCircle className="size-4 shrink-0" />
            <span>{errorMsg}</span>
          </div>
        )}
      </ConsoleCard>

      {mode !== 'property_nodes' && (
        <ConsoleCard padding="none" className="h-[520px] overflow-hidden">
          <GrafanaEmbed
            uid={GRAFANA_DASHBOARDS.process.uid}
            theme={isDark ? 'dark' : 'light'}
            title="Process Visualization"
            vars={{ topic: grafanaTopic }}
            from={grafanaTime.from}
            to={grafanaTime.to}
          />
        </ConsoleCard>
      )}

      <HistorianTable events={events} isLoading={loading} topicTitle={topicInput} />
      </PageContent>
    </PageShell>
  );
};

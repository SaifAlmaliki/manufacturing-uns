import React, { useState, useEffect, useCallback } from 'react';
import { RefreshCw, AlertCircle } from 'lucide-react';
import { useUNS } from '../../context/UNSContext';
import { HistoricEvent, BinaryOperator } from '../../types/uns';
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
  FilterToolbar,
  BtnPrimary,
  consoleTokens,
} from '../ui/console-ui';

type QueryMode = 'topic_time' | 'publishers' | 'property_event' | 'property_nodes';
type TimePreset = '5m' | '15m' | '1h' | '6h' | '24h' | 'all' | 'custom';

const MODE_TABS: { id: QueryMode; label: string }[] = [
  { id: 'topic_time', label: 'By Topic' },
  { id: 'publishers', label: 'By Publisher' },
  { id: 'property_event', label: 'By Property' },
  { id: 'property_nodes', label: 'Nodes by Property' },
];

const TIME_OPTIONS: { value: TimePreset; label: string }[] = [
  { value: '5m', label: 'Last 5m' },
  { value: '15m', label: 'Last 15m' },
  { value: '1h', label: 'Last 1h' },
  { value: '6h', label: 'Last 6h' },
  { value: '24h', label: 'Last 24h' },
  { value: 'all', label: 'All time' },
  { value: 'custom', label: 'Custom' },
];

export const ExploreView: React.FC = () => {
  const { historianInitialTopic, selectedNode } = useUNS();
  const { isDark } = useTheme();

  const [mode, setMode] = useState<QueryMode>('topic_time');
  const [topicInput, setTopicInput] = useState(
    historianInitialTopic || selectedNode?.topic || ''
  );

  const [timePreset, setTimePreset] = useState<TimePreset>('1h');
  const [customStartTime, setCustomStartTime] = useState(() => new Date(Date.now() - 3600 * 1000).toISOString().slice(0, 16));
  const [customEndTime, setCustomEndTime] = useState(() => new Date().toISOString().slice(0, 16));

  const [publishersInput, setPublishersInput] = useState('');

  const [propKeysInput, setPropKeysInput] = useState('site');
  const [propOperator, setPropOperator] = useState<BinaryOperator>('OR');
  const [excludeTopicsInput, setExcludeTopicsInput] = useState('spBv1.0/#');

  const [events, setEvents] = useState<HistoricEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

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

  const primarySearch =
    mode === 'topic_time'
      ? { value: topicInput, onChange: setTopicInput, placeholder: 'UNS topic…' }
      : mode === 'publishers'
        ? { value: publishersInput, onChange: setPublishersInput, placeholder: 'Publishers, comma-separated…' }
        : { value: propKeysInput, onChange: setPropKeysInput, placeholder: 'Property keys, comma-separated…' };

  const filterSelects = [
    ...(mode === 'property_event'
      ? [
          {
            value: propOperator,
            onChange: (value: string) => setPropOperator(value as BinaryOperator),
            'aria-label': 'Property operator',
            options: [
              { value: 'OR', label: 'OR' },
              { value: 'AND', label: 'AND' },
              { value: 'NOT', label: 'NOT' },
            ],
          },
        ]
      : []),
    ...(mode !== 'property_nodes'
      ? [
          {
            value: timePreset,
            onChange: (value: string) => setTimePreset(value as TimePreset),
            'aria-label': 'Time range',
            options: TIME_OPTIONS,
          },
        ]
      : []),
  ];

  return (
    <PageShell id="explore-historian-view" scroll={false} className="flex flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <PageContent fullWidth className="flex min-h-full flex-col gap-3 pb-4">
          <FilterToolbar
            tabs={{
              items: MODE_TABS,
              active: mode,
              onChange: (id) => setMode(id as QueryMode),
            }}
            search={primarySearch}
            selects={filterSelects}
            trailing={
              <>
                {mode === 'property_nodes' && (
                  <input
                    type="text"
                    value={excludeTopicsInput}
                    onChange={(e) => setExcludeTopicsInput(e.target.value)}
                    placeholder="Exclude topics…"
                    aria-label="Exclude topics"
                    className="min-w-[140px] flex-1 rounded-lg border-0 bg-zinc-800/60 px-2.5 py-1.5 text-sm text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:ring-1 focus:ring-[#FF7A00]/40"
                  />
                )}
                <BtnPrimary
                  id="execute-graphql-historian-query-btn"
                  onClick={runQuery}
                  disabled={loading}
                  className="px-2.5 py-1.5 text-xs"
                >
                  <RefreshCw className={`size-3.5 ${loading ? 'animate-spin' : ''}`} />
                  {loading ? 'Querying…' : 'Run Query'}
                </BtnPrimary>
              </>
            }
          />

          {timePreset === 'custom' && mode !== 'property_nodes' && (
            <div className="flex flex-wrap items-center gap-3 text-xs text-zinc-500">
              <label className="flex items-center gap-1.5">
                Start
                <input
                  type="datetime-local"
                  value={customStartTime}
                  onChange={(e) => setCustomStartTime(e.target.value)}
                  className={`${consoleTokens.input} w-auto py-1.5 text-xs`}
                />
              </label>
              <label className="flex items-center gap-1.5">
                End
                <input
                  type="datetime-local"
                  value={customEndTime}
                  onChange={(e) => setCustomEndTime(e.target.value)}
                  className={`${consoleTokens.input} w-auto py-1.5 text-xs`}
                />
              </label>
            </div>
          )}

          {errorMsg && (
            <div className="flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">
              <AlertCircle className="size-3.5 shrink-0" />
              <span>{errorMsg}</span>
            </div>
          )}

          {mode !== 'property_nodes' && (
            <ConsoleCard padding="none" className="h-[420px] overflow-hidden">
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
      </div>
    </PageShell>
  );
};

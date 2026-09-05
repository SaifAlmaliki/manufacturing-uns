import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Activity, AlertTriangle, Bell, Layers } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { useUNS } from '../../context/UNSContext';
import { useAlarms } from '../../context/AlarmContext';
import { unsGraphQLClient } from '../../services/graphql/client';
import type { GraphqlConnectivityServer } from '../../services/graphql/types';
import { filterTagsBySearch, tagInScope } from '../../lib/condition-monitoring/match-tags';
import { conditionKpis } from '../../lib/condition-monitoring/kpis';
import { extractSample, mergeSeries, type Sample } from '../../lib/condition-monitoring/series';
import { DEFAULT_TIME_RANGE, rangeWindow, type TimeRangePreset } from '../../lib/condition-monitoring/time-range';
import { AccessRestricted } from '../common/AccessRestricted';
import { UnsTreeView } from '../home/UnsTreeView';
import {
  BtnGhost,
  CompactKpiRow,
  FilterToolbar,
  PageContent,
  PageShell,
  PageStat,
} from '../ui/console-ui';
import { SignalCard } from './SignalCard';

export const ConditionMonitoringView: React.FC = () => {
  const { hasPermission } = useAuth();
  const { selectedNode } = useUNS();
  const { activeAlarms } = useAlarms();
  const navigate = useNavigate();
  const [servers, setServers] = useState<GraphqlConnectivityServer[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [scoped, setScoped] = useState(false);
  const [search, setSearch] = useState('');
  const [preset, setPreset] = useState<TimeRangePreset>(DEFAULT_TIME_RANGE);
  const [historianByTopic, setHistorianByTopic] = useState<Record<string, Sample[]>>({});
  const [liveByTopic, setLiveByTopic] = useState<Record<string, Sample[]>>({});
  const [liveTopics, setLiveTopics] = useState<Set<string>>(() => new Set());
  const [historianError, setHistorianError] = useState<string | null>(null);

  useEffect(() => {
    if (selectedNode) setScoped(true);
  }, [selectedNode]);

  useEffect(() => {
    if (!hasPermission('uns_tree')) return;
    void (async () => {
      try {
        setLoadError(null);
        const list = await unsGraphQLClient.getConnectivityServers('OPC_UA');
        setServers(list);
      } catch (err) {
        setLoadError(
          err instanceof Error ? err.message : 'Connectivity catalog could not be loaded.',
        );
        setServers([]);
      }
    })();
  }, [hasPermission]);

  const subscribed = servers.flatMap((s) => s.tags.filter((t) => t.subscribed));
  const scopedTags = subscribed.filter((t) => tagInScope(t, scoped ? selectedNode : null));
  const visible = filterTagsBySearch(scopedTags, search);
  const visibleTopicsKey = visible.map((t) => t.mqttTopic).join('|');
  const timeWindow = rangeWindow(preset, Date.now());

  useEffect(() => {
    const topics = visible.map((t) => t.mqttTopic);
    const { fromIso, toIso } = rangeWindow(preset, Date.now());
    let cancelled = false;
    setHistorianError(null);
    void Promise.all(
      topics.map(async (topic) => {
        try {
          const events = await unsGraphQLClient.getHistoricEvents(topic, fromIso, toIso);
          return {
            topic,
            samples: events
              .map((e) => extractSample(e.payload, e.timestamp))
              .filter((s): s is Sample => s !== null),
            error: null as string | null,
          };
        } catch (err: unknown) {
          return {
            topic,
            samples: [] as Sample[],
            error: err instanceof Error ? err.message : 'Historian query failed.',
          };
        }
      }),
    ).then((entries) => {
      if (cancelled) return;
      setHistorianByTopic(Object.fromEntries(entries.map((e) => [e.topic, e.samples])));
      setHistorianError(entries.find((e) => e.error)?.error ?? null);
    });
    return () => {
      cancelled = true;
    };
  }, [preset, visibleTopicsKey]);

  useEffect(() => {
    const topics = visible.map((t) => t.mqttTopic);
    if (topics.length === 0) return undefined;
    return unsGraphQLClient.subscribeMqttMessages(topics, (msg) => {
      const sample = extractSample(msg.payload, msg.timestamp);
      if (!sample) return;
      setLiveTopics((prev) => new Set(prev).add(msg.topic));
      setLiveByTopic((prev) => ({
        ...prev,
        [msg.topic]: [...(prev[msg.topic] ?? []), sample],
      }));
    });
  }, [visibleTopicsKey]);

  const latestByTopic = Object.fromEntries(
    visible.map((tag) => {
      const samples = mergeSeries(
        historianByTopic[tag.mqttTopic] ?? [],
        liveByTopic[tag.mqttTopic] ?? [],
        timeWindow.fromMs,
        Date.now(),
      );
      return [tag.mqttTopic, samples[samples.length - 1]];
    }),
  );
  const kpis = conditionKpis({
    tags: visible,
    latestByTopic,
    liveTopics,
    alarms: activeAlarms,
  });

  if (!hasPermission('uns_tree')) {
    return (
      <PageShell scroll={false}>
        <AccessRestricted featureKey="uns_tree" />
      </PageShell>
    );
  }

  let body: React.ReactNode = (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      {visible.map((tag) => {
        const samples = mergeSeries(
          historianByTopic[tag.mqttTopic] ?? [],
          liveByTopic[tag.mqttTopic] ?? [],
          timeWindow.fromMs,
          Date.now(),
        );
        const latest = samples[samples.length - 1];
        return (
          <SignalCard
            key={`${tag.serverId}:${tag.nodeId}`}
            tag={tag}
            samples={samples}
            latest={latest}
            fromMs={timeWindow.fromMs}
            toMs={timeWindow.toMs}
          />
        );
      })}
    </div>
  );
  if (loadError) {
    body = null;
  } else if (subscribed.length === 0) {
    body = (
      <p className="text-sm text-zinc-400">
        Subscribe tags in <Link to="/connectivity">Assets & Connectivity</Link>.
      </p>
    );
  } else if (search && visible.length === 0) {
    body = <p className="text-sm text-zinc-400">No signals match this search.</p>;
  } else if (scoped && visible.length === 0 && subscribed.length > 0 && !search) {
    body = <p className="text-sm text-zinc-400">No subscribed signals in this zone.</p>;
  }

  return (
    <PageShell id="condition-monitoring-view" scroll={false} className="flex flex-col">
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <section
          aria-label="UNS Hierarchy Tree"
          className="h-[300px] shrink-0 overflow-hidden border-b border-zinc-800 bg-[#111114] md:hidden"
        >
          <UnsTreeView />
        </section>
        <section
          aria-label="UNS Hierarchy Tree"
          className="hidden w-[280px] shrink-0 overflow-hidden border-r border-zinc-800 bg-[#111114] md:block"
        >
          <UnsTreeView />
        </section>
        <div className="min-h-0 min-w-0 flex-1 overflow-y-auto">
          <PageContent fullWidth className="flex min-h-full flex-col gap-3 pb-4">
            <CompactKpiRow>
              <PageStat
                compact
                label="In view"
                value={kpis.inView}
                icon={<Layers className="size-3.5 text-zinc-400" />}
              />
              <PageStat
                compact
                label="Live"
                value={kpis.live}
                icon={<Activity className="size-3.5 text-zinc-400" />}
              />
              <PageStat
                compact
                label="Faults on"
                value={kpis.faultsOn}
                icon={<AlertTriangle className="size-3.5 text-zinc-400" />}
              />
              <button
                type="button"
                aria-label="Unacked"
                className="rounded-lg border-0 bg-transparent p-0 text-left"
                onClick={() => navigate('/alerts')}
              >
                <PageStat
                  compact
                  label="Unacked"
                  value={kpis.unacked}
                  icon={<Bell className="size-3.5 text-zinc-400" />}
                />
              </button>
              <button
                type="button"
                aria-label="Critical"
                className="rounded-lg border-0 bg-transparent p-0 text-left"
                onClick={() => navigate('/alerts')}
              >
                <PageStat
                  compact
                  label="Critical"
                  value={kpis.critical}
                  icon={<AlertTriangle className="size-3.5 text-red-400" />}
                  iconBg="bg-red-500/15"
                />
              </button>
            </CompactKpiRow>
            {loadError ? (
              <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
                {loadError}
              </div>
            ) : null}
            {historianError ? (
              <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
                {historianError}
              </div>
            ) : null}
            <FilterToolbar
              search={{ value: search, onChange: setSearch, placeholder: 'Search name or topic…' }}
              selects={[
                {
                  value: preset,
                  onChange: (v) => setPreset(v as TimeRangePreset),
                  'aria-label': 'Time range',
                  options: [
                    { value: '15m', label: 'Last 15 minutes' },
                    { value: '60m', label: 'Last 60 minutes' },
                    { value: '4h', label: 'Last 4 hours' },
                    { value: '24h', label: 'Last 24 hours' },
                  ],
                },
              ]}
              trailing={
                scoped ? (
                  <BtnGhost type="button" onClick={() => setScoped(false)}>
                    All signals
                  </BtnGhost>
                ) : null
              }
            />
            {body}
          </PageContent>
        </div>
      </div>
    </PageShell>
  );
};

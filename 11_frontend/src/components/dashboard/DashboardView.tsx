import React, { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Layers,
  AlertTriangle,
  Bell,
  Radio,
  Activity,
  Search,
} from 'lucide-react';
import { useUNS } from '../../context/UNSContext';
import { useAlarms } from '../../context/AlarmContext';
import { MqttMessage } from '../../types/uns';
import {
  PageShell,
  PageContent,
  ConsoleCard,
  CompactKpiRow,
  PageStat,
  BtnGhost,
  BtnPrimary,
} from '../ui/console-ui';

function bucketMessagesByMinute(feed: MqttMessage[], buckets = 12): number[] {
  const now = Date.now();
  const counts = Array(buckets).fill(0);
  for (const msg of feed) {
    const age = now - new Date(msg.timestamp).getTime();
    const bucketIndex = Math.floor(age / 60000);
    if (bucketIndex >= 0 && bucketIndex < buckets) {
      counts[buckets - 1 - bucketIndex] += 1;
    }
  }
  return counts.reverse();
}

function formatTopicShort(topic: string): string {
  const parts = topic.split('/');
  return parts.length > 2 ? parts.slice(-2).join(' / ') : topic;
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

export const DashboardView: React.FC = () => {
  const navigate = useNavigate();
  const { allLoadedNodes, staleNodesCount, mqttFeed, health } = useUNS();
  const { totalUnacknowledgedCount, activeAlarms, rules, isPlatformLive } = useAlarms();

  const activeNodes = allLoadedNodes.length - staleNodesCount;
  const messageBuckets = useMemo(() => bucketMessagesByMinute(mqttFeed), [mqttFeed]);
  const messagesPerMin = messageBuckets[messageBuckets.length - 1] ?? 0;

  const alarmBySeverity = useMemo(() => {
    const counts = { CRITICAL: 0, HIGH: 0, WARNING: 0, INFO: 0 };
    for (const a of activeAlarms) {
      if (a.status === 'ACTIVE_UNACK' || a.status === 'ACTIVE_ACK') {
        counts[a.severity] += 1;
      }
    }
    return counts;
  }, [activeAlarms]);

  const alarmTotal = Object.values(alarmBySeverity).reduce((s, v) => s + v, 0);
  const alarmSegments = [
    { label: 'Critical', value: alarmBySeverity.CRITICAL, color: '#ef4444' },
    { label: 'High', value: alarmBySeverity.HIGH, color: '#f97316' },
    { label: 'Warning', value: alarmBySeverity.WARNING, color: '#eab308' },
    { label: 'Info', value: alarmBySeverity.INFO, color: '#71717a' },
  ];

  const recentMessages = mqttFeed.slice(0, 6);

  const healthScore = health.status === 'LIVE' ? 100 : health.status === 'DEGRADED' ? 72 : 35;
  const nodeHealthPct = allLoadedNodes.length > 0 ? Math.round((activeNodes / allLoadedNodes.length) * 100) : 100;
  const alarmAckPct =
    totalUnacknowledgedCount + activeAlarms.length > 0
      ? Math.round(((activeAlarms.length - totalUnacknowledgedCount) / activeAlarms.length) * 100)
      : 100;
  const rulesActivePct = rules.length > 0 ? Math.round((rules.filter((r) => r.enabled).length / rules.length) * 100) : 0;

  const maxBucket = Math.max(...messageBuckets, 1);

  return (
    <PageShell id="dashboard-view" scroll={false} className="flex flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <PageContent fullWidth className="flex min-h-full flex-col gap-3 pb-4">
          <CompactKpiRow
            actions={
              <>
                <BtnGhost onClick={() => navigate('/tree')} className="px-2.5 py-1.5 text-xs">
                  <Layers className="size-3.5" />
                  Tree
                </BtnGhost>
                <BtnGhost onClick={() => navigate('/historian')} className="px-2.5 py-1.5 text-xs">
                  <Search className="size-3.5" />
                  Historian
                </BtnGhost>
                <BtnGhost onClick={() => navigate('/alerts')} className="px-2.5 py-1.5 text-xs">
                  <Bell className="size-3.5" />
                  Alarms
                </BtnGhost>
                <BtnPrimary onClick={() => navigate('/system')} className="px-2.5 py-1.5 text-xs">
                  <Activity className="size-3.5" />
                  System
                </BtnPrimary>
              </>
            }
          >
            <button type="button" onClick={() => navigate('/tree')} className="text-left">
              <PageStat compact label="Active Nodes" value={activeNodes} icon={<Layers className="size-3.5 text-[#FF7A00]" />} />
            </button>
            <button type="button" onClick={() => navigate('/tree')} className="text-left">
              <PageStat compact label="Msg / min" value={messagesPerMin} icon={<Radio className="size-3.5 text-emerald-400" />} iconBg="bg-emerald-500/15" />
            </button>
            <button type="button" onClick={() => navigate('/alerts')} className="text-left">
              <PageStat
                compact
                label="Open Alarms"
                value={isPlatformLive ? totalUnacknowledgedCount : '—'}
                valueClassName={!isPlatformLive ? 'text-zinc-400' : totalUnacknowledgedCount > 0 ? 'text-red-400' : 'text-white'}
                icon={<Bell className={`size-3.5 ${totalUnacknowledgedCount > 0 ? 'text-red-400' : 'text-zinc-400'}`} />}
                iconBg={totalUnacknowledgedCount > 0 ? 'bg-red-500/15' : 'bg-zinc-800'}
              />
            </button>
            <button type="button" onClick={() => navigate('/tree')} className="text-left">
              <PageStat
                compact
                label="Stale Nodes"
                value={staleNodesCount}
                valueClassName={staleNodesCount > 0 ? 'text-amber-400' : 'text-white'}
                icon={<AlertTriangle className={`size-3.5 ${staleNodesCount > 0 ? 'text-amber-400' : 'text-zinc-400'}`} />}
                iconBg={staleNodesCount > 0 ? 'bg-amber-500/15' : 'bg-zinc-800'}
              />
            </button>
          </CompactKpiRow>

          <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
            <ConsoleCard padding="sm" className="lg:col-span-2">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-semibold text-white">Message Activity</h2>
                <span className="rounded-lg border border-zinc-800 bg-zinc-900 px-2 py-0.5 text-[10px] text-zinc-400">
                  Live · 12 min
                </span>
              </div>
              <div className="flex h-36 items-end gap-1.5">
                {messageBuckets.map((count, i) => (
                  <div key={i} className="group flex flex-1 flex-col items-center gap-1.5">
                    <div className="relative w-full">
                      <div
                        className="w-full rounded-t-md bg-[#FF7A00]/80 transition-all group-hover:bg-[#FF7A00]"
                        style={{ height: `${Math.max(8, (count / maxBucket) * 120)}px` }}
                      />
                      {count > 0 && (
                        <div className="pointer-events-none absolute -top-7 left-1/2 hidden -translate-x-1/2 rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] text-zinc-200 group-hover:block">
                          {count} msgs
                        </div>
                      )}
                    </div>
                    <span className="text-[10px] tabular-nums text-zinc-600">-{11 - i}m</span>
                  </div>
                ))}
              </div>
            </ConsoleCard>

            <ConsoleCard padding="sm">
              <h2 className="mb-3 text-sm font-semibold text-white">Alarm Breakdown</h2>
              {alarmTotal === 0 ? (
                <div className="flex h-36 flex-col items-center justify-center text-zinc-500">
                  <Bell className="mb-1.5 size-6 opacity-40" />
                  <span className="text-xs">No active alarms</span>
                </div>
              ) : (
                <div className="flex items-center gap-4">
                  <div className="relative size-28 shrink-0">
                    <svg viewBox="0 0 36 36" className="size-full -rotate-90">
                      {(() => {
                        let offset = 0;
                        return alarmSegments.map((seg) => {
                          const pct = (seg.value / alarmTotal) * 100;
                          const dash = `${pct} ${100 - pct}`;
                          const el = (
                            <circle
                              key={seg.label}
                              cx="18"
                              cy="18"
                              r="15.9"
                              fill="none"
                              stroke={seg.color}
                              strokeWidth="4"
                              strokeDasharray={dash}
                              strokeDashoffset={-offset}
                            />
                          );
                          offset += pct;
                          return el;
                        });
                      })()}
                    </svg>
                    <div className="absolute inset-0 flex flex-col items-center justify-center">
                      <span className="text-lg font-semibold tabular-nums text-white">{alarmTotal}</span>
                      <span className="text-[10px] text-zinc-500">active</span>
                    </div>
                  </div>
                  <div className="min-w-0 flex-1 space-y-1.5">
                    {alarmSegments.map((seg) => (
                      <div key={seg.label} className="flex items-center justify-between text-xs">
                        <div className="flex items-center gap-2">
                          <span className="size-2 rounded-full" style={{ backgroundColor: seg.color }} />
                          <span className="text-zinc-400">{seg.label}</span>
                        </div>
                        <span className="font-medium tabular-nums text-zinc-200">{seg.value}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </ConsoleCard>
          </div>

          <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
            <ConsoleCard padding="sm">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-semibold text-white">Recent Events</h2>
                <button
                  type="button"
                  onClick={() => navigate('/tree')}
                  className="text-xs font-medium text-[#FF7A00] hover:text-[#ff9533]"
                >
                  View All
                </button>
              </div>
              <div className="space-y-2">
                {recentMessages.length === 0 ? (
                  <p className="py-6 text-center text-xs text-zinc-500">Waiting for MQTT messages…</p>
                ) : (
                  recentMessages.map((msg) => (
                    <div key={msg.id} className="flex items-center gap-2.5 rounded-lg border border-zinc-800/60 bg-zinc-900/40 px-2.5 py-2">
                      <div className="flex size-7 shrink-0 items-center justify-center rounded-md bg-[#FF7A00]/15">
                        <Radio className="size-3.5 text-[#FF7A00]" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-xs font-medium text-zinc-200">{formatTopicShort(msg.topic)}</div>
                        <div className="text-[10px] text-zinc-500">{formatTime(msg.timestamp)}</div>
                      </div>
                      <span className="shrink-0 rounded-md bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-medium text-emerald-400">
                        Live
                      </span>
                    </div>
                  ))
                )}
              </div>
            </ConsoleCard>

            <ConsoleCard padding="sm">
              <h2 className="mb-3 text-sm font-semibold text-white">Platform Health</h2>
              <div className="mb-3 flex items-baseline gap-2">
                <span className="text-2xl font-semibold tabular-nums text-white">{healthScore}%</span>
                <span
                  className={`text-xs font-medium ${
                    health.status === 'LIVE' ? 'text-emerald-400' : health.status === 'DEGRADED' ? 'text-amber-400' : 'text-red-400'
                  }`}
                >
                  {health.status}
                </span>
              </div>
              <div className="space-y-2">
                {[
                  { label: 'GraphQL HTTP', ok: health.graphqlHttp },
                  { label: 'GraphQL WebSocket', ok: health.graphqlWs },
                  { label: 'Data Mode', ok: health.mode === 'LIVE_GRAPHQL' },
                ].map((item) => (
                  <div key={item.label} className="flex items-center justify-between text-xs">
                    <span className="text-zinc-400">{item.label}</span>
                    <span className={item.ok ? 'text-emerald-400' : 'text-amber-400'}>
                      {item.ok ? 'Connected' : 'Fallback'}
                    </span>
                  </div>
                ))}
                <div className="flex items-center justify-between text-xs">
                  <span className="text-zinc-400">Latency</span>
                  <span className="tabular-nums text-zinc-200">{health.lastPingMs} ms</span>
                </div>
              </div>
            </ConsoleCard>

            <ConsoleCard padding="sm">
              <h2 className="mb-3 text-sm font-semibold text-white">Operational Targets</h2>
              <div className="space-y-3">
                {[
                  { label: 'Node Freshness', pct: nodeHealthPct, detail: `${activeNodes} / ${allLoadedNodes.length} nodes` },
                  { label: 'Alarm Acknowledgement', pct: alarmAckPct, detail: `${totalUnacknowledgedCount} unacknowledged` },
                  {
                    label: 'Rules Active',
                    pct: rulesActivePct,
                    detail: `${rules.filter((r) => r.enabled).length} / ${rules.length} rules`,
                  },
                ].map((goal) => (
                  <div key={goal.label}>
                    <div className="mb-1 flex items-center justify-between text-xs">
                      <span className="text-zinc-400">{goal.label}</span>
                      <span className="font-medium tabular-nums text-white">{goal.pct}%</span>
                    </div>
                    <div className="h-1.5 overflow-hidden rounded-full bg-zinc-800">
                      <div className="h-full rounded-full bg-[#FF7A00] transition-all" style={{ width: `${goal.pct}%` }} />
                    </div>
                    <div className="mt-0.5 text-[10px] text-zinc-600">{goal.detail}</div>
                  </div>
                ))}
              </div>
            </ConsoleCard>
          </div>
        </PageContent>
      </div>
    </PageShell>
  );
};

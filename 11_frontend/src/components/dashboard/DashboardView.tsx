import React, { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Layers,
  AlertTriangle,
  Bell,
  Radio,
  Activity,
  Search,
  ArrowUpRight,
  ArrowDownRight,
  ChevronRight,
  TrendingUp,
} from 'lucide-react';
import { useUNS } from '../../context/UNSContext';
import { useAlarms } from '../../context/AlarmContext';
import { MqttMessage } from '../../types/uns';

/* ── Sparkline (simple SVG polyline) ── */

function Sparkline({ points, color }: { points: number[]; color: string }) {
  const max = Math.max(...points, 1);
  const w = 80;
  const h = 32;
  const coords = points
    .map((v, i) => {
      const x = (i / (points.length - 1)) * w;
      const y = h - (v / max) * h;
      return `${x},${y}`;
    })
    .join(' ');

  return (
    <svg width={w} height={h} className="opacity-80">
      <polyline fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" points={coords} />
    </svg>
  );
}

/* ── Stat card ── */

interface StatCardProps {
  label: string;
  value: string | number;
  trend?: { direction: 'up' | 'down' | 'neutral'; label: string };
  sparkColor: string;
  sparkPoints: number[];
  icon: React.ReactNode;
  iconBg: string;
  onClick?: () => void;
}

function StatCard({ label, value, trend, sparkColor, sparkPoints, icon, iconBg, onClick }: StatCardProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full flex-col rounded-2xl border border-zinc-800 bg-[#111114] p-5 text-left transition-colors hover:border-zinc-700"
    >
      <div className="mb-4 flex items-start justify-between">
        <div className={`flex size-10 items-center justify-center rounded-xl ${iconBg}`}>{icon}</div>
        <Sparkline points={sparkPoints} color={sparkColor} />
      </div>
      <div className="text-sm text-zinc-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums text-white">{value}</div>
      {trend && (
        <div
          className={`mt-2 flex items-center gap-1 text-xs font-medium ${
            trend.direction === 'up'
              ? 'text-emerald-400'
              : trend.direction === 'down'
                ? 'text-red-400'
                : 'text-zinc-500'
          }`}
        >
          {trend.direction === 'up' && <ArrowUpRight className="size-3.5" />}
          {trend.direction === 'down' && <ArrowDownRight className="size-3.5" />}
          {trend.label}
        </div>
      )}
    </button>
  );
}

/* ── Helpers ── */

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

/* ── Main dashboard ── */

export const DashboardView: React.FC = () => {
  const navigate = useNavigate();
  const { allLoadedNodes, staleNodesCount, mqttFeed, health, settings, bookmarks } = useUNS();
  const { myUnacknowledgedCount, totalUnacknowledgedCount, activeAlarms, rules, criticalAlarmsCount, isPlatformLive } = useAlarms();

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
    <div className="flex-1 overflow-y-auto bg-[#0a0a0b] p-4 md:p-6">
      <div className="mx-auto max-w-[1400px] space-y-6">
        {/* Summary cards */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard
            label="Active Nodes"
            value={activeNodes}
            trend={{ direction: staleNodesCount === 0 ? 'up' : 'neutral', label: `${allLoadedNodes.length} total in namespace` }}
            sparkColor="#FF7A00"
            sparkPoints={messageBuckets.length ? messageBuckets : [0, 0, 0, 0, 0, 0]}
            icon={<Layers className="size-5 text-[#FF7A00]" />}
            iconBg="bg-[#FF7A00]/15"
            onClick={() => navigate('/tree')}
          />
          <StatCard
            label="Messages / min"
            value={messagesPerMin}
            trend={{ direction: messagesPerMin > 0 ? 'up' : 'neutral', label: 'Live MQTT throughput' }}
            sparkColor="#22c55e"
            sparkPoints={messageBuckets.length ? messageBuckets : [0, 0, 0, 0, 0, 0]}
            icon={<Radio className="size-5 text-emerald-400" />}
            iconBg="bg-emerald-500/15"
            onClick={() => navigate('/tree')}
          />
          <StatCard
            label="Open Alarms"
            value={isPlatformLive ? totalUnacknowledgedCount : '—'}
            trend={{
              direction: !isPlatformLive ? 'neutral' : totalUnacknowledgedCount > 0 ? 'down' : 'up',
              label: !isPlatformLive
                ? 'Platform offline'
                : criticalAlarmsCount > 0
                  ? `${criticalAlarmsCount} critical`
                  : 'All clear',
            }}
            sparkColor="#ef4444"
            sparkPoints={
              isPlatformLive
                ? [totalUnacknowledgedCount, myUnacknowledgedCount, criticalAlarmsCount, 0, 0, 0, 0, 0, 0, 0, 0, 0]
                : [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
            }
            icon={<Bell className="size-5 text-red-400" />}
            iconBg="bg-red-500/15"
            onClick={() => navigate('/alerts')}
          />
          <StatCard
            label="Stale Nodes"
            value={staleNodesCount}
            trend={{
              direction: staleNodesCount > 0 ? 'down' : 'up',
              label: staleNodesCount > 0 ? `>${settings.staleThresholdMinutes} min silent` : 'All nodes fresh',
            }}
            sparkColor="#f97316"
            sparkPoints={[staleNodesCount, staleNodesCount, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]}
            icon={<AlertTriangle className="size-5 text-amber-400" />}
            iconBg="bg-amber-500/15"
            onClick={() => navigate('/tree')}
          />
        </div>

        {/* Charts row */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          {/* Message activity */}
          <div className="rounded-2xl border border-zinc-800 bg-[#111114] p-5 lg:col-span-2">
            <div className="mb-5 flex items-center justify-between">
              <div>
                <h2 className="text-base font-semibold text-white">Message Activity</h2>
                <p className="text-sm text-zinc-500">MQTT events over the last 12 minutes</p>
              </div>
              <span className="rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-xs text-zinc-400">Live</span>
            </div>
            <div className="flex h-44 items-end gap-2">
              {messageBuckets.map((count, i) => (
                <div key={i} className="group flex flex-1 flex-col items-center gap-2">
                  <div className="relative w-full">
                    <div
                      className="w-full rounded-t-lg bg-[#FF7A00]/80 transition-all group-hover:bg-[#FF7A00]"
                      style={{ height: `${Math.max(8, (count / maxBucket) * 140)}px` }}
                    />
                    {count > 0 && (
                      <div className="pointer-events-none absolute -top-8 left-1/2 hidden -translate-x-1/2 rounded bg-zinc-800 px-2 py-1 text-[10px] text-zinc-200 group-hover:block">
                        {count} msgs
                      </div>
                    )}
                  </div>
                  <span className="text-[10px] text-zinc-600 tabular-nums">-{11 - i}m</span>
                </div>
              ))}
            </div>
          </div>

          {/* Alarm breakdown */}
          <div className="rounded-2xl border border-zinc-800 bg-[#111114] p-5">
            <div className="mb-5">
              <h2 className="text-base font-semibold text-white">Alarm Breakdown</h2>
              <p className="text-sm text-zinc-500">Active alarms by severity</p>
            </div>
            {alarmTotal === 0 ? (
              <div className="flex h-44 flex-col items-center justify-center text-zinc-500">
                <Bell className="mb-2 size-8 opacity-40" />
                <span className="text-sm">No active alarms</span>
              </div>
            ) : (
              <div className="flex items-center gap-5">
                <div className="relative size-32 shrink-0">
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
                    <span className="text-xl font-semibold tabular-nums text-white">{alarmTotal}</span>
                    <span className="text-[10px] text-zinc-500">active</span>
                  </div>
                </div>
                <div className="min-w-0 flex-1 space-y-2">
                  {alarmSegments.map((seg) => (
                    <div key={seg.label} className="flex items-center justify-between text-sm">
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
          </div>
        </div>

        {/* Bottom row */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          {/* Recent events */}
          <div className="rounded-2xl border border-zinc-800 bg-[#111114] p-5">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-base font-semibold text-white">Recent Events</h2>
              <button
                onClick={() => navigate('/tree')}
                className="text-xs font-medium text-[#FF7A00] hover:text-[#ff9533]"
              >
                View All
              </button>
            </div>
            <div className="space-y-3">
              {recentMessages.length === 0 ? (
                <p className="py-6 text-center text-sm text-zinc-500">Waiting for MQTT messages…</p>
              ) : (
                recentMessages.map((msg) => (
                  <div key={msg.id} className="flex items-center gap-3 rounded-xl border border-zinc-800/60 bg-zinc-900/40 px-3 py-2.5">
                    <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-[#FF7A00]/15">
                      <Radio className="size-4 text-[#FF7A00]" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium text-zinc-200">{formatTopicShort(msg.topic)}</div>
                      <div className="text-xs text-zinc-500">{formatTime(msg.timestamp)}</div>
                    </div>
                    <span className="shrink-0 rounded-md bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium text-emerald-400">
                      Live
                    </span>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Platform health */}
          <div className="rounded-2xl border border-zinc-800 bg-[#111114] p-5">
            <div className="mb-4">
              <h2 className="text-base font-semibold text-white">Platform Health</h2>
              <p className="text-sm text-zinc-500">Subsystem connectivity</p>
            </div>
            <div className="mb-4 flex items-baseline gap-2">
              <span className="text-3xl font-semibold tabular-nums text-white">{healthScore}%</span>
              <span
                className={`text-sm font-medium ${
                  health.status === 'LIVE' ? 'text-emerald-400' : health.status === 'DEGRADED' ? 'text-amber-400' : 'text-red-400'
                }`}
              >
                {health.status}
              </span>
            </div>
            <div className="space-y-3">
              {[
                { label: 'GraphQL HTTP', ok: health.graphqlHttp },
                { label: 'GraphQL WebSocket', ok: health.graphqlWs },
                { label: 'Data Mode', ok: health.mode === 'LIVE_GRAPHQL' },
              ].map((item) => (
                <div key={item.label} className="flex items-center justify-between text-sm">
                  <span className="text-zinc-400">{item.label}</span>
                  <span className={item.ok ? 'text-emerald-400' : 'text-amber-400'}>
                    {item.ok ? 'Connected' : 'Fallback'}
                  </span>
                </div>
              ))}
              <div className="flex items-center justify-between text-sm">
                <span className="text-zinc-400">Latency</span>
                <span className="tabular-nums text-zinc-200">{health.lastPingMs} ms</span>
              </div>
            </div>
          </div>

          {/* Goals / progress */}
          <div className="rounded-2xl border border-zinc-800 bg-[#111114] p-5">
            <div className="mb-4">
              <h2 className="text-base font-semibold text-white">Operational Targets</h2>
              <p className="text-sm text-zinc-500">Plant namespace health goals</p>
            </div>
            <div className="space-y-5">
              {[
                { label: 'Node Freshness', pct: nodeHealthPct, detail: `${activeNodes} / ${allLoadedNodes.length} nodes` },
                { label: 'Alarm Acknowledgement', pct: alarmAckPct, detail: `${totalUnacknowledgedCount} unacknowledged` },
                { label: 'Rules Active', pct: rulesActivePct, detail: `${rules.filter((r) => r.enabled).length} / ${rules.length} rules` },
              ].map((goal) => (
                <div key={goal.label}>
                  <div className="mb-1.5 flex items-center justify-between text-sm">
                    <span className="text-zinc-400">{goal.label}</span>
                    <span className="font-medium tabular-nums text-white">{goal.pct}%</span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-zinc-800">
                    <div
                      className="h-full rounded-full bg-[#FF7A00] transition-all"
                      style={{ width: `${goal.pct}%` }}
                    />
                  </div>
                  <div className="mt-1 text-xs text-zinc-600">{goal.detail}</div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Quick links + insights banner */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            { label: 'UNS Tree', icon: Layers, to: '/tree' },
            { label: 'Historian', icon: Search, to: '/historian' },
            { label: 'Alarms', icon: Bell, to: '/alerts' },
            { label: 'System', icon: Activity, to: '/system' },
          ].map((link) => (
            <button
              key={link.to}
              onClick={() => navigate(link.to)}
              className="flex items-center gap-3 rounded-xl border border-zinc-800 bg-[#111114] px-4 py-3 text-sm font-medium text-zinc-300 transition-colors hover:border-[#FF7A00]/40 hover:text-white"
            >
              <link.icon className="size-4 text-[#FF7A00]" />
              {link.label}
              <ChevronRight className="ml-auto size-4 text-zinc-600" />
            </button>
          ))}
        </div>

        <div className="flex flex-col items-start justify-between gap-4 rounded-2xl border border-zinc-800 bg-[#111114] p-5 sm:flex-row sm:items-center">
          <div className="flex items-start gap-4">
            <div className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-[#FF7A00]/15">
              <TrendingUp className="size-6 text-[#FF7A00]" />
            </div>
            <div>
              <h3 className="font-semibold text-white">Platform Insights</h3>
              <p className="mt-1 max-w-xl text-sm text-zinc-400">
                {health.status === 'LIVE'
                  ? `Your namespace is live with ${allLoadedNodes.length} nodes and ${messagesPerMin} messages per minute. ${bookmarks.length} bookmarks saved for quick access.`
                  : 'Platform is running in degraded mode. Check System Health for connection details.'}
              </p>
            </div>
          </div>
          <button
            onClick={() => navigate('/system')}
            className="shrink-0 rounded-xl bg-[#FF7A00] px-5 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-[#e66e00]"
          >
            View Detailed Report
          </button>
        </div>
      </div>
    </div>
  );
};

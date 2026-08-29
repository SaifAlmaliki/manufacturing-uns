import React from 'react';
import {
  Activity,
  Server,
  Database,
  Workflow,
  Radio,
  Layers,
  FileCode,
  Sliders,
  Shield,
  Lock,
} from 'lucide-react';
import { useUNS } from '../../context/UNSContext';
import { useAuth } from '../../context/AuthContext';

export const SystemHealthView: React.FC = () => {
  const { health, settings, updateSettings } = useUNS();
  const { hasPermission, currentUser, isAdmin } = useAuth();
  const canEditSettings = hasPermission('settings_edit');

  return (
    <div id="system-health-view" className="flex-1 overflow-y-auto p-6 space-y-6 bg-[#050505] text-[#F8FAFC] font-mono text-xs max-w-6xl mx-auto">
      {/* Top Header */}
      <div className="flex items-center justify-between pb-4 border-b border-[#1E293B]">
        <div>
          <h1 className="text-sm font-bold text-[#F8FAFC] uppercase tracking-wider flex items-center gap-2">
            <Activity className="w-4 h-4 text-[#FFC107]" />
            <span>Unified Namespace System Health &amp; Ops</span>
          </h1>
          <p className="text-[10px] text-[#64748B] mt-1 font-mono">
            07_uns_graphql connectivity, subsystem status, and RBAC authorization matrix
          </p>
        </div>

        <div className="flex items-center gap-2">
          <span className="px-2.5 py-1 rounded bg-[#111114] border border-[#1E293B] text-[10px] text-[#94A3B8]">
            Mode: <b className="text-[#FFC107]">{health.mode}</b>
          </span>
          <span className="px-2.5 py-1 rounded bg-[#111114] border border-[#1E293B] text-[10px] text-[#94A3B8]">
            Latency: <b className="text-[#10B981]">{health.lastPingMs} ms</b>
          </span>
        </div>
      </div>

      {/* Grid of Subsystems */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {/* GraphQL API Gateway */}
        <div className="p-3.5 rounded-lg bg-[#111114] border border-[#1E293B] space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Server className="w-4 h-4 text-[#FFC107]" />
              <span className="font-bold text-[#F8FAFC] text-xs">07_uns_graphql</span>
            </div>
            <span
              className={`px-2 py-0.5 rounded text-[9px] font-bold ${
                health.graphqlHttp ? 'bg-emerald-950 text-emerald-300 border border-emerald-800' : 'bg-amber-950 text-amber-300 border border-amber-800'
              }`}
            >
              {health.graphqlHttp ? 'HTTP 200 OK' : 'SIMULATION FALLBACK'}
            </span>
          </div>
          <p className="text-[10px] text-[#64748B]">
            Primary HTTP/WS GraphQL gateway endpoint: <code className="text-[#FFC107]">{settings.graphqlUrl}</code>
          </p>
        </div>

        {/* RBAC & User Management Gateway */}
        <div className="p-3.5 rounded-lg bg-[#111114] border border-rose-500/30 space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Shield className="w-4 h-4 text-rose-400" />
              <span className="font-bold text-[#F8FAFC] text-xs">RBAC &amp; Access Control</span>
            </div>
            <span className="px-2 py-0.5 rounded text-[9px] bg-rose-950/80 border border-rose-800 text-rose-300 font-bold">
              ENFORCED (ZERO-TRUST)
            </span>
          </div>
          <p className="text-[10px] text-[#64748B]">
            Active Identity: <b className="text-[#F8FAFC]">{currentUser.name}</b> ({currentUser.role.toUpperCase()}) &bull; Admin controls active.
          </p>
        </div>

        {/* MQTT Broker (Phase 3 pending status) */}
        <div className="p-3.5 rounded-lg bg-[#111114] border border-[#1E293B] space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Radio className="w-4 h-4 text-[#10B981]" />
              <span className="font-bold text-[#F8FAFC] text-xs">MQTT Broker</span>
            </div>
            <span className="px-2 py-0.5 rounded text-[9px] bg-[#0B0B0C] border border-[#1E293B] text-[#FFC107] font-bold">
              SCHEMA PENDING
            </span>
          </div>
          <p className="text-[10px] text-[#64748B]">
            Phase 3: Direct broker health query pending GraphQL backend schema integration.
          </p>
        </div>

        {/* Neo4j Current Tree (Phase 3 pending status) */}
        <div className="p-3.5 rounded-lg bg-[#111114] border border-[#1E293B] space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Layers className="w-4 h-4 text-[#38BDF8]" />
              <span className="font-bold text-[#F8FAFC] text-xs">Neo4j Graph Tree</span>
            </div>
            <span className="px-2 py-0.5 rounded text-[9px] bg-[#0B0B0C] border border-[#1E293B] text-[#FFC107] font-bold">
              SCHEMA PENDING
            </span>
          </div>
          <p className="text-[10px] text-[#64748B]">
            UNS node hierarchy queried via <code className="text-[#38BDF8]">getUnsNodes</code>. Subsystem health check pending.
          </p>
        </div>

        {/* TimescaleDB Historian (Phase 3 pending status) */}
        <div className="p-3.5 rounded-lg bg-[#111114] border border-[#1E293B] space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Database className="w-4 h-4 text-purple-400" />
              <span className="font-bold text-[#F8FAFC] text-xs">TimescaleDB Historian</span>
            </div>
            <span className="px-2 py-0.5 rounded text-[9px] bg-[#0B0B0C] border border-[#1E293B] text-[#FFC107] font-bold">
              SCHEMA PENDING
            </span>
          </div>
          <p className="text-[10px] text-[#64748B]">
            Time-series telemetry events queried via <code className="text-purple-300">getHistoricEvents</code>.
          </p>
        </div>

        {/* Sparkplug B Mapper */}
        <div className="p-3.5 rounded-lg bg-[#111114] border border-[#1E293B] space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Radio className="w-4 h-4 text-[#A855F7]" />
              <span className="font-bold text-[#F8FAFC] text-xs">Sparkplug B Mapper</span>
            </div>
            <span className="px-2 py-0.5 rounded text-[9px] bg-emerald-950 border border-emerald-800 text-emerald-300 font-bold">
              ACTIVE
            </span>
          </div>
          <p className="text-[10px] text-[#64748B]">
            Server-side protobuf mapper active. Metrics decoded via <code className="text-purple-300">getSpbNodesByMetric</code>.
          </p>
        </div>
      </div>

      {/* Phase 3 & 4 GraphQL Schema Capabilities Status Matrix */}
      <div className="p-4 rounded-lg bg-[#111114] border border-[#1E293B] space-y-3 shadow-lg">
        <h3 className="font-bold text-[#F8FAFC] text-xs uppercase tracking-wider flex items-center gap-2">
          <FileCode className="w-4 h-4 text-[#FFC107]" />
          <span>GraphQL Schema Capabilities Matrix</span>
        </h3>

        <div className="divide-y divide-[#1E293B]">
          <div className="py-2.5 flex items-center justify-between">
            <div>
              <span className="text-[#F8FAFC] font-semibold text-xs">Authentication &amp; RBAC Access Control Console</span>
              <p className="text-[10px] text-[#64748B]">
                Granular feature matrix, user directory, audit trails &amp; admin permission provisioning.
              </p>
            </div>
            <span className="px-2 py-0.5 rounded bg-emerald-950/60 border border-emerald-800/60 text-emerald-300 text-[9px] font-bold">
              OPERATIONAL
            </span>
          </div>

          <div className="py-2.5 flex items-center justify-between">
            <div>
              <span className="text-[#F8FAFC] font-semibold text-xs">CSV Data Exporter</span>
              <p className="text-[10px] text-[#64748B]">Client-side CSV generation from loaded historian rows with RBAC authorization guard.</p>
            </div>
            <span className="px-2 py-0.5 rounded bg-emerald-950/60 border border-emerald-800/60 text-emerald-300 text-[9px] font-bold">
              OPERATIONAL
            </span>
          </div>

          <div className="py-2.5 flex items-center justify-between">
            <div>
              <span className="text-[#F8FAFC] font-semibold text-xs">Topic Bookmarks &amp; Stale Node Alerts</span>
              <p className="text-[10px] text-[#64748B]">LocalStorage topic persistence and &gt;5 min lastUpdated node alerts.</p>
            </div>
            <span className="px-2 py-0.5 rounded bg-emerald-950/60 border border-emerald-800/60 text-emerald-300 text-[9px] font-bold">
              OPERATIONAL
            </span>
          </div>

          <div className="py-2.5 flex items-center justify-between">
            <div>
              <span className="text-[#F8FAFC] font-semibold text-xs">Historian Cursor/Page Pagination</span>
              <p className="text-[10px] text-[#64748B]">
                Phase 3: Schema limitation today. Historian returns batch results by time window.
              </p>
            </div>
            <span className="px-2 py-0.5 rounded bg-amber-950/60 border border-amber-800/60 text-amber-400 text-[9px] font-bold">
              BLOCKED (SCHEMA PENDING)
            </span>
          </div>

          <div className="py-2.5 flex items-center justify-between">
            <div>
              <span className="text-[#F8FAFC] font-semibold text-xs">Subsystem Health &amp; Ops Queries</span>
              <p className="text-[10px] text-[#64748B]">
                Phase 3: Unified health query for MQTT, Neo4j, Timescale, and Kafka.
              </p>
            </div>
            <span className="px-2 py-0.5 rounded bg-amber-950/60 border border-amber-800/60 text-amber-400 text-[9px] font-bold">
              BLOCKED (SCHEMA PENDING)
            </span>
          </div>
        </div>
      </div>

      {/* Local Application Preferences Form with RBAC Protection */}
      <div className="p-4 rounded-lg bg-[#111114] border border-[#1E293B] space-y-3 shadow-lg">
        <div className="flex items-center justify-between">
          <h3 className="font-bold text-[#F8FAFC] text-xs uppercase tracking-wider flex items-center gap-2">
            <Sliders className="w-4 h-4 text-[#FFC107]" />
            <span>Console Configuration &amp; Branding (conf/settings.yaml)</span>
          </h3>
          {!canEditSettings && (
            <span className="px-2 py-0.5 rounded bg-[#1E293B] border border-[#334155] text-[#94A3B8] text-[9px] flex items-center gap-1">
              <Lock className="w-3 h-3 text-rose-400" />
              <span>Read-Only Mode</span>
            </span>
          )}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <label className="text-[#94A3B8] text-[10px] block mb-1">DISPLAY NAME:</label>
            <input
              type="text"
              disabled={!canEditSettings}
              value={settings.displayName}
              onChange={(e) => updateSettings({ displayName: e.target.value })}
              className={`w-full bg-[#0B0B0C] border border-[#1E293B] rounded px-2.5 py-1.5 text-[#F8FAFC] text-[11px] focus:outline-none focus:border-[#FFC107] ${
                !canEditSettings ? 'opacity-60 cursor-not-allowed' : ''
              }`}
            />
          </div>

          <div>
            <label className="text-[#94A3B8] text-[10px] block mb-1">ORGANIZATION:</label>
            <input
              type="text"
              disabled={!canEditSettings}
              value={settings.organization}
              onChange={(e) => updateSettings({ organization: e.target.value })}
              className={`w-full bg-[#0B0B0C] border border-[#1E293B] rounded px-2.5 py-1.5 text-[#F8FAFC] text-[11px] focus:outline-none focus:border-[#FFC107] ${
                !canEditSettings ? 'opacity-60 cursor-not-allowed' : ''
              }`}
            />
          </div>

          <div>
            <label className="text-[#94A3B8] text-[10px] block mb-1">INSTANCE / LOCATION:</label>
            <input
              type="text"
              disabled={!canEditSettings}
              value={settings.instance}
              onChange={(e) => updateSettings({ instance: e.target.value })}
              className={`w-full bg-[#0B0B0C] border border-[#1E293B] rounded px-2.5 py-1.5 text-[#F8FAFC] text-[11px] focus:outline-none focus:border-[#FFC107] ${
                !canEditSettings ? 'opacity-60 cursor-not-allowed' : ''
              }`}
            />
          </div>

          <div>
            <label className="text-[#94A3B8] text-[10px] block mb-1">STALE THRESHOLD (MINUTES):</label>
            <input
              type="number"
              disabled={!canEditSettings}
              value={settings.staleThresholdMinutes}
              onChange={(e) => updateSettings({ staleThresholdMinutes: Number(e.target.value) || 5 })}
              className={`w-full bg-[#0B0B0C] border border-[#1E293B] rounded px-2.5 py-1.5 text-[#F8FAFC] text-[11px] focus:outline-none focus:border-[#FFC107] ${
                !canEditSettings ? 'opacity-60 cursor-not-allowed' : ''
              }`}
            />
          </div>
        </div>
      </div>
    </div>
  );
};

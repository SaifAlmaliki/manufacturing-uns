import React, { useState } from 'react';
import { Activity, RefreshCw, Server, Wifi } from 'lucide-react';
import { useUNS } from '../../context/UNSContext';

export const ConnectionChip: React.FC = () => {
  const { health, settings, updateSettings, refreshTree } = useUNS();
  const [isOpen, setIsOpen] = useState(false);
  const [customHttpUrl, setCustomHttpUrl] = useState(settings.graphqlUrl);
  const [customWsUrl, setCustomWsUrl] = useState(settings.graphqlWsUrl);
  const [isTesting, setIsTesting] = useState(false);

  const getStatusColor = () => {
    switch (health.status) {
      case 'LIVE':
        return 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-300 dark:border-emerald-500/30';
      case 'DEGRADED':
        return 'bg-amber-50 dark:bg-amber-500/10 text-amber-800 dark:text-[#FFC107] border-amber-300 dark:border-amber-500/30';
      case 'DOWN':
        return 'bg-rose-50 dark:bg-rose-500/10 text-rose-700 dark:text-rose-400 border-rose-300 dark:border-rose-500/30';
    }
  };

  const getStatusDot = () => {
    switch (health.status) {
      case 'LIVE':
        return 'bg-emerald-500 dark:bg-emerald-400 shadow-[0_0_8px_rgba(16,185,129,0.5)]';
      case 'DEGRADED':
        return 'bg-amber-500 dark:bg-[#FFC107] shadow-[0_0_8px_rgba(245,158,11,0.5)]';
      case 'DOWN':
        return 'bg-rose-500 shadow-[0_0_8px_rgba(239,68,68,0.5)]';
    }
  };

  const handleApplyUrls = async () => {
    setIsTesting(true);
    updateSettings({
      graphqlUrl: customHttpUrl,
      graphqlWsUrl: customWsUrl,
    });
    await refreshTree();
    setTimeout(() => {
      setIsTesting(false);
      setIsOpen(false);
    }, 600);
  };

  return (
    <div className="relative">
      <button
        id="connection-status-chip"
        onClick={() => setIsOpen(!isOpen)}
        className={`flex items-center gap-2 px-2.5 py-1 rounded-md border text-[11px] font-mono font-medium transition-all ${getStatusColor()} hover:bg-slate-100 dark:hover:bg-[#1E293B] cursor-pointer`}
        title="GraphQL 07_uns_graphql connection status (Click for details)"
      >
        <span className={`w-2 h-2 rounded-full animate-pulse ${getStatusDot()}`} />
        <span className="font-semibold tracking-wider">{health.status}</span>
        <span className="text-[10px] opacity-75 hidden sm:inline">
          {health.mode === 'LIVE_GRAPHQL' ? `${health.lastPingMs}ms` : 'SIM'}
        </span>
      </button>

      {/* Popover overlay */}
      {isOpen && (
        <div
          id="connection-details-popover"
          className="absolute right-0 mt-2 w-80 bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] rounded-lg shadow-xl z-50 p-4 text-xs font-mono animate-in fade-in zoom-in-95 duration-150"
        >
          <div className="flex items-center justify-between pb-3 border-b border-[#E2E8F0] dark:border-[#1E293B]">
            <div className="flex items-center gap-2">
              <Server className="w-4 h-4 text-amber-600 dark:text-[#FFC107]" />
              <span className="font-bold text-[#0F172A] dark:text-[#F8FAFC] text-xs uppercase tracking-wider">07_uns_graphql Status</span>
            </div>
            <span className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold border ${getStatusColor()}`}>
              {health.status}
            </span>
          </div>

          {/* Subsystem checklist */}
          <div className="py-3 space-y-2 border-b border-[#E2E8F0] dark:border-[#1E293B] font-mono text-[10px]">
            <div className="flex items-center justify-between text-[#475569] dark:text-[#94A3B8]">
              <span className="flex items-center gap-1.5">
                <Activity className="w-3.5 h-3.5 text-[#64748B]" />
                <span>GraphQL HTTP Engine:</span>
              </span>
              <span className={health.graphqlHttp ? 'text-emerald-600 dark:text-emerald-400 font-bold' : 'text-amber-600 dark:text-[#FFC107]'}>
                {health.graphqlHttp ? 'Connected (200 OK)' : 'Fallback Mock Engine'}
              </span>
            </div>

            <div className="flex items-center justify-between text-[#475569] dark:text-[#94A3B8]">
              <span className="flex items-center gap-1.5">
                <Wifi className="w-3.5 h-3.5 text-[#64748B]" />
                <span>GraphQL WS Stream:</span>
              </span>
              <span className={health.graphqlWs ? 'text-emerald-600 dark:text-emerald-400 font-bold' : 'text-amber-600 dark:text-[#FFC107]'}>
                {health.graphqlWs ? 'Subscribed' : 'Simulated Reactive Feed'}
              </span>
            </div>

            <div className="flex items-center justify-between text-[#64748B] pt-1 text-[10px]">
              <span>Round-trip latency:</span>
              <span className="text-amber-600 dark:text-[#FFC107] font-semibold">{health.lastPingMs} ms</span>
            </div>

            <div className="flex items-center justify-between text-[#64748B] text-[10px]">
              <span>Data source mode:</span>
              <span className="text-[#0F172A] dark:text-[#F8FAFC] font-semibold">{health.mode}</span>
            </div>
          </div>

          {/* Configuration Form */}
          <div className="pt-3 space-y-2">
            <div className="text-[#64748B] text-[10px] uppercase font-bold tracking-wider">Endpoint Configuration</div>
            <div>
              <label className="block text-[#475569] dark:text-[#94A3B8] text-[10px] mb-1 font-mono">HTTP GRAPHQL URL:</label>
              <input
                type="text"
                value={customHttpUrl}
                onChange={(e) => setCustomHttpUrl(e.target.value)}
                placeholder="/graphql or http://localhost:8000/graphql"
                className="w-full bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#CBD5E1] dark:border-[#1E293B] rounded px-2.5 py-1 text-[#0F172A] dark:text-[#F8FAFC] font-mono text-[11px] focus:outline-none focus:border-amber-500 dark:focus:border-[#FFC107]"
              />
            </div>

            <div>
              <label className="block text-[#475569] dark:text-[#94A3B8] text-[10px] mb-1 font-mono">WEBSOCKET URL:</label>
              <input
                type="text"
                value={customWsUrl}
                onChange={(e) => setCustomWsUrl(e.target.value)}
                placeholder="ws://localhost:8000/graphql"
                className="w-full bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#CBD5E1] dark:border-[#1E293B] rounded px-2.5 py-1 text-[#0F172A] dark:text-[#F8FAFC] font-mono text-[11px] focus:outline-none focus:border-amber-500 dark:focus:border-[#FFC107]"
              />
            </div>

            <div className="flex items-center gap-2 pt-2">
              <button
                onClick={handleApplyUrls}
                disabled={isTesting}
                className="flex-1 bg-amber-500 hover:bg-amber-600 dark:bg-[#FFC107] dark:hover:bg-[#FFB300] disabled:opacity-50 text-slate-900 font-bold py-1.5 rounded transition-colors flex items-center justify-center gap-1.5 cursor-pointer text-xs shadow-xs"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${isTesting ? 'animate-spin' : ''}`} />
                <span>{isTesting ? 'Connecting...' : 'Reconnect & Apply'}</span>
              </button>
              <button
                onClick={() => setIsOpen(false)}
                className="px-3 py-1.5 bg-[#F1F5F9] dark:bg-[#0B0B0C] border border-[#CBD5E1] dark:border-[#1E293B] hover:bg-slate-200 dark:hover:bg-[#1E293B] text-[#475569] dark:text-[#94A3B8] rounded transition-colors cursor-pointer text-xs"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

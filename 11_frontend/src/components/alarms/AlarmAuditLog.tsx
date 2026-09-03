import React, { useState } from 'react';
import { Download, Search, AlertTriangle, FileText } from 'lucide-react';
import { useAlarms } from '../../context/AlarmContext';
import { AlarmAuditEntry } from '../../types/alarm';
import { ROLE_CONFIGS } from '../../types/rbac';
import { BtnSecondary, ConsoleCard, consoleTokens } from '../ui/console-ui';

export const AlarmAuditLog: React.FC = () => {
  const { auditLog, isPlatformLive, rulesError } = useAlarms();
  const [searchQuery, setSearchQuery] = useState('');
  const [actionFilter, setActionFilter] = useState('ALL');
  const [severityFilter, setSeverityFilter] = useState('ALL');

  const filteredLogs = auditLog.filter((entry) => {
    if (actionFilter !== 'ALL' && entry.action !== actionFilter) return false;
    if (severityFilter !== 'ALL' && entry.severity !== severityFilter) return false;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      return (
        entry.ruleName.toLowerCase().includes(q) ||
        entry.topic.toLowerCase().includes(q) ||
        entry.actorName.toLowerCase().includes(q) ||
        entry.details.toLowerCase().includes(q)
      );
    }
    return true;
  });

  const exportCSV = () => {
    const headers = ['Timestamp', 'Action', 'Severity', 'Rule Name', 'Topic', 'Actor Name', 'Actor Role', 'Details'];
    const rows = filteredLogs.map((log) => [
      `"${log.timestamp}"`,
      `"${log.action}"`,
      `"${log.severity}"`,
      `"${log.ruleName.replace(/"/g, '""')}"`,
      `"${log.topic.replace(/"/g, '""')}"`,
      `"${log.actorName.replace(/"/g, '""')}"`,
      `"${log.actorRole}"`,
      `"${log.details.replace(/"/g, '""')}"`,
    ]);

    const csvContent = [headers.join(','), ...rows.map((r) => r.join(','))].join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.setAttribute('href', url);
    link.setAttribute('download', `uns-alarm-audit-${new Date().toISOString().slice(0, 10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const getActionBadge = (action: AlarmAuditEntry['action']) => {
    switch (action) {
      case 'TRIGGERED':
        return 'border-rose-500/40 bg-rose-500/15 text-rose-300';
      case 'ACKNOWLEDGED':
        return 'border-amber-500/40 bg-amber-500/15 text-amber-300';
      case 'RESOLVED':
        return 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300';
      case 'RULE_UPDATED':
        return 'border-sky-500/40 bg-sky-500/15 text-sky-300';
      default:
        return 'border-zinc-700 bg-zinc-800 text-zinc-400';
    }
  };

  return (
    <div className="space-y-2">
      <ConsoleCard padding="sm" className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[200px] flex-1">
          <Search className="absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-zinc-500" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search audit trail…"
            className={consoleTokens.input + ' py-1.5 pl-8 text-xs'}
          />
        </div>
        <select
          value={actionFilter}
          onChange={(e) => setActionFilter(e.target.value)}
          className={consoleTokens.input + ' w-auto py-1.5 text-xs'}
        >
          <option value="ALL">All Actions</option>
          <option value="TRIGGERED">Triggered</option>
          <option value="ACKNOWLEDGED">Acknowledged</option>
          <option value="RESOLVED">Resolved</option>
          <option value="RULE_UPDATED">Rule Updated</option>
          <option value="CLEARED">Cleared</option>
        </select>
        <select
          value={severityFilter}
          onChange={(e) => setSeverityFilter(e.target.value)}
          className={consoleTokens.input + ' w-auto py-1.5 text-xs'}
        >
          <option value="ALL">All Severities</option>
          <option value="CRITICAL">Critical</option>
          <option value="HIGH">High</option>
          <option value="WARNING">Warning</option>
          <option value="INFO">Info</option>
        </select>
        <BtnSecondary onClick={exportCSV} className="px-2.5 py-1.5 text-xs">
          <Download className="size-3.5" />
          Export CSV
        </BtnSecondary>
      </ConsoleCard>

      <ConsoleCard padding="none" className="overflow-hidden">
        {!isPlatformLive ? (
          <div className="flex min-h-[min(360px,calc(100dvh-14rem))] flex-col items-center justify-center gap-2 p-8 text-center">
            <AlertTriangle className="size-10 text-rose-400 opacity-80" />
            <p className="text-sm font-semibold text-rose-200">Platform offline</p>
            <p className="max-w-md text-xs text-rose-300/80 font-mono text-pretty">
              {rulesError ?? 'Audit entries are recorded only while the platform is connected.'}
            </p>
          </div>
        ) : filteredLogs.length === 0 ? (
          <div className="flex min-h-[min(360px,calc(100dvh-14rem))] flex-col items-center justify-center gap-2 p-8 text-center">
            <FileText className="size-10 text-zinc-500 opacity-50" />
            <p className="text-sm font-semibold text-white">No audit entries yet</p>
            <p className="max-w-md text-xs text-zinc-500 text-pretty">
              Rule changes and live alarm lifecycle events will appear here.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] border-collapse text-left text-xs">
              <thead>
                <tr className="border-b border-zinc-800 bg-zinc-900/80 font-mono text-[10px] uppercase text-zinc-500">
                  <th className="px-3 py-2">Timestamp</th>
                  <th className="px-3 py-2">Action</th>
                  <th className="px-3 py-2">Severity</th>
                  <th className="px-3 py-2">Rule &amp; Topic</th>
                  <th className="px-3 py-2">Actor</th>
                  <th className="px-3 py-2">Details</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800/80 font-mono text-[11px]">
                {filteredLogs.map((entry) => {
                  const actorRoleCfg = ROLE_CONFIGS[entry.actorRole] || ROLE_CONFIGS.viewer;

                  return (
                    <tr key={entry.id} className="transition-colors hover:bg-zinc-800/30">
                      <td className="whitespace-nowrap px-3 py-2 tabular-nums text-zinc-500">
                        {new Date(entry.timestamp).toLocaleString()}
                      </td>
                      <td className="px-3 py-2">
                        <span className={`rounded border px-2 py-0.5 text-[10px] font-bold ${getActionBadge(entry.action)}`}>
                          {entry.action}
                        </span>
                      </td>
                      <td className="px-3 py-2 font-semibold text-white">{entry.severity}</td>
                      <td className="max-w-xs px-3 py-2">
                        <div className="truncate font-semibold text-white">{entry.ruleName}</div>
                        <div className="truncate text-[10px] text-zinc-500">{entry.topic}</div>
                      </td>
                      <td className="whitespace-nowrap px-3 py-2">
                        <div className="font-semibold text-white">{entry.actorName}</div>
                        <span
                          className={`rounded border px-1.5 py-0.5 text-[9px] ${actorRoleCfg.badgeBg} ${actorRoleCfg.badgeText} ${actorRoleCfg.badgeBorder}`}
                        >
                          {entry.actorRole.toUpperCase()}
                        </span>
                      </td>
                      <td className="max-w-md px-3 py-2 text-zinc-400 text-pretty">{entry.details}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </ConsoleCard>
    </div>
  );
};

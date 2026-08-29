import React, { useState } from 'react';
import {
  Clock,
  Download,
  Search,
  Filter,
  Shield,
  CheckCircle2,
  AlertTriangle,
  FileText,
  UserCheck,
} from 'lucide-react';
import { useAlarms } from '../../context/AlarmContext';
import { AlarmAuditEntry, AlarmSeverity } from '../../types/alarm';
import { ROLE_CONFIGS, UserRole } from '../../types/rbac';

export const AlarmAuditLog: React.FC = () => {
  const { auditLog } = useAlarms();
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
        return 'bg-rose-500/20 text-rose-300 border-rose-500/40';
      case 'ACKNOWLEDGED':
        return 'bg-amber-500/20 text-amber-300 border-amber-500/40';
      case 'RESOLVED':
        return 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40';
      case 'RULE_UPDATED':
        return 'bg-sky-500/20 text-sky-300 border-sky-500/40';
      default:
        return 'bg-[#1E293B] text-[#94A3B8] border-[#334155]';
    }
  };

  return (
    <div className="space-y-4 font-sans text-xs">
      {/* Header & Controls */}
      <div className="bg-[#111114] border border-[#1E293B] rounded-lg p-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-display font-bold text-sm text-[#F8FAFC]">
            Alarm Lifecycle Audit Trail
          </h2>
          <p className="text-[11px] text-[#94A3B8]">
            Tamper-evident chronological log of threshold breach events, operator acknowledgements, and configuration changes.
          </p>
        </div>

        <button
          onClick={exportCSV}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-[#1E293B] hover:bg-[#334155] text-[#FFC107] border border-[#334155] rounded-lg text-xs font-mono font-bold transition-colors cursor-pointer"
        >
          <Download className="w-4 h-4" />
          <span>Export Audit CSV</span>
        </button>
      </div>

      {/* Filter Row */}
      <div className="bg-[#111114] border border-[#1E293B] rounded-lg p-3 flex flex-wrap items-center justify-between gap-2.5">
        <div className="relative flex-1 min-w-[220px]">
          <Search className="w-3.5 h-3.5 text-[#64748B] absolute left-2.5 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search audit trail by actor, topic, rule, or action details..."
            className="w-full bg-[#0B0B0C] border border-[#1E293B] rounded-md pl-8 pr-2 py-1.5 text-xs text-[#F8FAFC] font-mono focus:outline-none focus:border-[#FFC107]"
          />
        </div>

        <div className="flex items-center gap-2">
          <select
            value={actionFilter}
            onChange={(e) => setActionFilter(e.target.value)}
            className="bg-[#0B0B0C] border border-[#1E293B] rounded-md px-2.5 py-1.5 text-xs text-[#94A3B8] font-mono focus:outline-none focus:border-[#FFC107] cursor-pointer"
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
            className="bg-[#0B0B0C] border border-[#1E293B] rounded-md px-2.5 py-1.5 text-xs text-[#94A3B8] font-mono focus:outline-none focus:border-[#FFC107] cursor-pointer"
          >
            <option value="ALL">All Severities</option>
            <option value="CRITICAL">Critical</option>
            <option value="HIGH">High</option>
            <option value="WARNING">Warning</option>
            <option value="INFO">Info</option>
          </select>
        </div>
      </div>

      {/* Audit Log Table */}
      <div className="bg-[#111114] border border-[#1E293B] rounded-xl overflow-hidden shadow-lg">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="border-b border-[#1E293B] bg-[#0B0B0C] text-[#64748B] font-mono text-[10px] uppercase">
                <th className="py-3 px-3">Timestamp</th>
                <th className="py-3 px-3">Action</th>
                <th className="py-3 px-3">Severity</th>
                <th className="py-3 px-3">Rule &amp; Target Topic</th>
                <th className="py-3 px-3">Actor &amp; Role</th>
                <th className="py-3 px-3">Event Details</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#1E293B]/60 font-mono text-[11px]">
              {filteredLogs.map((entry) => {
                const actorRoleCfg = ROLE_CONFIGS[entry.actorRole] || ROLE_CONFIGS.viewer;

                return (
                  <tr key={entry.id} className="hover:bg-[#1E293B]/20 transition-colors">
                    {/* Timestamp */}
                    <td className="py-2.5 px-3 text-[#64748B] whitespace-nowrap">
                      {new Date(entry.timestamp).toLocaleString()}
                    </td>

                    {/* Action */}
                    <td className="py-2.5 px-3">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold border ${getActionBadge(entry.action)}`}>
                        {entry.action}
                      </span>
                    </td>

                    {/* Severity */}
                    <td className="py-2.5 px-3">
                      <span className="text-[#F8FAFC] font-semibold">{entry.severity}</span>
                    </td>

                    {/* Rule & Topic */}
                    <td className="py-2.5 px-3 max-w-xs">
                      <div className="font-bold text-[#F8FAFC] truncate">{entry.ruleName}</div>
                      <div className="text-[10px] text-[#64748B] truncate">{entry.topic}</div>
                    </td>

                    {/* Actor */}
                    <td className="py-2.5 px-3 whitespace-nowrap">
                      <div className="text-[#F8FAFC] font-semibold">{entry.actorName}</div>
                      <span className={`text-[9px] px-1.5 py-0.2 rounded border ${actorRoleCfg.badgeBg} ${actorRoleCfg.badgeText} ${actorRoleCfg.badgeBorder}`}>
                        {entry.actorRole.toUpperCase()}
                      </span>
                    </td>

                    {/* Details */}
                    <td className="py-2.5 px-3 text-[#94A3B8] max-w-md">
                      {entry.details}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

import React, { useState, useEffect } from 'react';
import {
  AlertTriangle,
  Bell,
  CheckCircle2,
  X,
  Volume2,
  VolumeX,
  Plus,
  Sliders,
  Shield,
  Layers,
  Search,
  Filter,
  CheckCheck,
  RefreshCw,
  TrendingUp,
  Clock,
  Sparkles,
  UserCheck,
  ExternalLink,
  Database,
  MonitorSmartphone,
} from 'lucide-react';
import { useAlarms } from '../../context/AlarmContext';
import { useAuth } from '../../context/AuthContext';
import { useUNS } from '../../context/UNSContext';
import { ActiveAlarm, AlarmSeverity, AlertRule } from '../../types/alarm';
import { UserRole, ROLE_CONFIGS } from '../../types/rbac';
import { AlertRuleEditorModal } from './AlertRuleEditorModal';
import { RoleAlertMatrix } from './RoleAlertMatrix';
import { AlarmAuditLog } from './AlarmAuditLog';
import {
  PageShell,
  PageContent,
  ConsoleCard,
  PageStat,
  SegmentTabs,
  BtnPrimary,
  BtnSecondary,
  BtnGhost,
} from '../ui/console-ui';

type AlarmSubTab = 'active' | 'rules' | 'matrix' | 'audit';

export const AlarmManagementView: React.FC = () => {
  const {
    rules,
    activeAlarms,
    myRoleAlarms,
    myUnacknowledgedCount,
    totalUnacknowledgedCount,
    criticalAlarmsCount,
    isMuted,
    toggleAudioMute,
    acknowledgeAlarm,
    resolveAlarm,
    bulkAcknowledgeAll,
    testTriggerRule,
    toggleRuleEnabled,
    deleteRule,
    clearResolvedAlarms,
    rulesOrigin,
    rulesError,
    refreshRules,
  } = useAlarms();

  const { currentUser, isAdmin } = useAuth();
  const { jumpToHistorian, jumpToTopicInTree } = useUNS();

  const [activeSubTab, setActiveSubTab] = useState<AlarmSubTab>('active');
  const [roleFilter, setRoleFilter] = useState<'my_role' | 'all'>('my_role');
  const [severityFilter, setSeverityFilter] = useState<string>('ALL');
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Modals & Ack dialog state
  const [editingRule, setEditingRule] = useState<AlertRule | null>(null);
  const [isRuleModalOpen, setIsRuleModalOpen] = useState(false);
  const [acknowledgingAlarm, setAcknowledgingAlarm] = useState<ActiveAlarm | null>(null);
  const [ackNotes, setAckNotes] = useState('');
  const [resolvingAlarm, setResolvingAlarm] = useState<ActiveAlarm | null>(null);
  const [resolveNotes, setResolveNotes] = useState('');

  // Determine displayed alarms based on filter
  const displayedAlarms = (roleFilter === 'my_role' ? myRoleAlarms : activeAlarms).filter((alarm) => {
    if (severityFilter !== 'ALL' && alarm.severity !== severityFilter) return false;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      return (
        alarm.ruleName.toLowerCase().includes(q) ||
        alarm.topic.toLowerCase().includes(q) ||
        alarm.conditionDescription.toLowerCase().includes(q) ||
        alarm.status.toLowerCase().includes(q)
      );
    }
    return true;
  });

  const getSeverityBadge = (sev: AlarmSeverity) => {
    switch (sev) {
      case 'CRITICAL':
        return 'bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-500/20 dark:text-rose-300 dark:border-rose-500/50';
      case 'HIGH':
        return 'bg-amber-50 text-amber-800 border-amber-200 dark:bg-amber-500/20 dark:text-amber-300 dark:border-amber-500/50';
      case 'WARNING':
        return 'bg-yellow-50 text-yellow-800 border-yellow-200 dark:bg-yellow-500/20 dark:text-yellow-300 dark:border-yellow-500/50';
      case 'INFO':
        return 'bg-sky-50 text-sky-700 border-sky-200 dark:bg-sky-500/20 dark:text-sky-300 dark:border-sky-500/50';
    }
  };

  const getStatusBadge = (status: ActiveAlarm['status']) => {
    switch (status) {
      case 'ACTIVE_UNACK':
        return 'bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950/60 dark:text-rose-400 dark:border-rose-700/60 animate-pulse';
      case 'ACTIVE_ACK':
        return 'bg-amber-50 text-amber-800 border-amber-200 dark:bg-amber-950/60 dark:text-amber-400 dark:border-amber-700/60';
      case 'CLEARED_UNACK':
        return 'bg-sky-50 text-sky-700 border-sky-200 dark:bg-sky-950/60 dark:text-sky-400 dark:border-sky-700/60';
      case 'RESOLVED':
        return 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/60 dark:text-emerald-400 dark:border-emerald-700/60';
    }
  };

  const handleOpenCreateRule = () => {
    setEditingRule(null);
    setIsRuleModalOpen(true);
  };

  const handleOpenEditRule = (rule: AlertRule) => {
    setEditingRule(rule);
    setIsRuleModalOpen(true);
  };

  const handleConfirmAck = () => {
    if (acknowledgingAlarm) {
      acknowledgeAlarm(acknowledgingAlarm.id, ackNotes);
      setAcknowledgingAlarm(null);
      setAckNotes('');
    }
  };

  const handleConfirmResolve = () => {
    if (resolvingAlarm) {
      resolveAlarm(resolvingAlarm.id, resolveNotes);
      setResolvingAlarm(null);
      setResolveNotes('');
    }
  };

  const alarmTabs = [
    { id: 'active', label: 'Active Incidents', icon: Bell, badge: myUnacknowledgedCount || undefined },
    { id: 'rules', label: 'Alert Rules', icon: Sliders, badge: rules.length },
    { id: 'matrix', label: 'Role Matrix', icon: Shield },
    { id: 'audit', label: 'Audit Trail', icon: Clock },
  ];

  return (
    <PageShell id="alarm-management-view" scroll={false} className="flex flex-col">
      <PageContent className="shrink-0 space-y-4 pb-4">
        <ConsoleCard className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-3">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-red-500/15">
              <Bell className="size-5 text-red-400" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-white">Alarm Management</h2>
              <p className="text-sm text-zinc-500">Real-time threshold alerts and incident lifecycle</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <BtnGhost onClick={toggleAudioMute} title={isMuted ? 'Unmute' : 'Mute audio'}>
              {isMuted ? <VolumeX className="size-4 text-red-400" /> : <Volume2 className="size-4 text-[#FF7A00]" />}
              <span>{isMuted ? 'Muted' : 'Audio On'}</span>
            </BtnGhost>
            {myUnacknowledgedCount > 0 && (
              <BtnSecondary id="bulk-ack-alarms-btn" onClick={() => bulkAcknowledgeAll()}>
                <CheckCheck className="size-4" />
                Ack All ({myUnacknowledgedCount})
              </BtnSecondary>
            )}
            <BtnPrimary id="create-alert-rule-btn" onClick={handleOpenCreateRule}>
              <Plus className="size-4" />
              New Rule
            </BtnPrimary>
          </div>
        </ConsoleCard>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <PageStat label="Critical" value={criticalAlarmsCount} valueClassName={criticalAlarmsCount > 0 ? 'text-red-400' : 'text-white'} icon={<AlertTriangle className="size-5 text-red-400" />} iconBg="bg-red-500/15" />
          <PageStat label="My Pending" value={myUnacknowledgedCount} valueClassName={myUnacknowledgedCount > 0 ? 'text-[#FF7A00]' : 'text-white'} icon={<UserCheck className="size-5 text-[#FF7A00]" />} />
          <PageStat label="Plant Active" value={activeAlarms.filter((a) => a.status !== 'RESOLVED').length} icon={<Bell className="size-5 text-zinc-400" />} iconBg="bg-zinc-800" />
          <PageStat label="Rules Active" value={`${rules.filter((r) => r.enabled).length} / ${rules.length}`} valueClassName="text-emerald-400" icon={<Sliders className="size-5 text-emerald-400" />} iconBg="bg-emerald-500/15" />
        </div>

        <SegmentTabs tabs={alarmTabs} active={activeSubTab} onChange={(id) => setActiveSubTab(id as AlarmSubTab)} />
      </PageContent>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4 md:px-6 md:pb-6">
        {activeSubTab === 'active' && (
          <div className="space-y-4">
            {/* Filter Bar */}
            <ConsoleCard className="flex flex-wrap items-center justify-between gap-3">
              {/* Left: Role Scope Switcher */}
              <div className="flex items-center gap-1 bg-[#F1F5F9] dark:bg-[#0B0B0C] p-1 rounded-lg border border-[#E2E8F0] dark:border-[#1E293B]">
                <button
                  onClick={() => setRoleFilter('my_role')}
                  className={`px-3 py-1.5 rounded text-xs font-mono transition-all cursor-pointer ${
                    roleFilter === 'my_role'
                      ? 'bg-amber-500 dark:bg-[#FFC107] text-[#0B0B0C] font-bold shadow-sm'
                      : 'text-[#64748B] dark:text-[#94A3B8] hover:text-[#0F172A] dark:hover:text-[#F8FAFC]'
                  }`}
                >
                  My Role Alerts ({currentUser.role})
                </button>
                <button
                  onClick={() => setRoleFilter('all')}
                  className={`px-3 py-1.5 rounded text-xs font-mono transition-all cursor-pointer ${
                    roleFilter === 'all'
                      ? 'bg-amber-500 dark:bg-[#FFC107] text-[#0B0B0C] font-bold shadow-sm'
                      : 'text-[#64748B] dark:text-[#94A3B8] hover:text-[#0F172A] dark:hover:text-[#F8FAFC]'
                  }`}
                >
                  All Plant Alarms ({activeAlarms.length})
                </button>
              </div>

              {/* Right: Severity Dropdown & Search & Clear Resolved */}
              <div className="flex items-center gap-2 flex-1 sm:flex-initial min-w-[280px]">
                <div className="relative flex-1">
                  <Search className="w-3.5 h-3.5 text-[#64748B] absolute left-2.5 top-1/2 -translate-y-1/2" />
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Filter incidents..."
                    className="w-full bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#CBD5E1] dark:border-[#1E293B] rounded-md pl-8 pr-2 py-1.5 text-xs text-[#0F172A] dark:text-[#F8FAFC] font-mono focus:outline-none focus:border-amber-500 dark:focus:border-[#FFC107]"
                  />
                </div>

                <select
                  value={severityFilter}
                  onChange={(e) => setSeverityFilter(e.target.value)}
                  className="bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#CBD5E1] dark:border-[#1E293B] rounded-md px-2.5 py-1.5 text-xs text-[#475569] dark:text-[#94A3B8] font-mono focus:outline-none focus:border-amber-500 dark:focus:border-[#FFC107] cursor-pointer"
                >
                  <option value="ALL">All Severities</option>
                  <option value="CRITICAL">Critical</option>
                  <option value="HIGH">High</option>
                  <option value="WARNING">Warning</option>
                  <option value="INFO">Info</option>
                </select>

                <button
                  onClick={clearResolvedAlarms}
                  className="px-2.5 py-1.5 rounded bg-white dark:bg-[#0B0B0C] border border-[#CBD5E1] dark:border-[#1E293B] text-[#64748B] dark:text-[#94A3B8] hover:text-[#0F172A] dark:hover:text-[#F8FAFC] text-xs font-mono transition-colors cursor-pointer shrink-0"
                  title="Clear resolved alarms from view"
                >
                  Clear Resolved
                </button>
              </div>
            </ConsoleCard>

            {/* Alarms List */}
            {displayedAlarms.length === 0 ? (
              <div className="bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] rounded-xl p-12 text-center text-[#64748B] space-y-3">
                <CheckCircle2 className="w-12 h-12 text-emerald-500 dark:text-emerald-400 mx-auto opacity-70" />
                <h3 className="font-bold text-[#0F172A] dark:text-[#F8FAFC] text-sm text-balance">No Active Incidents</h3>
                <p className="text-xs text-[#64748B] dark:text-[#94A3B8] max-w-md mx-auto text-pretty">
                  {roleFilter === 'my_role'
                    ? `No active alarms routed to role '${currentUser.role}'. Plant is running within normal parameters.`
                    : 'All ISA-95 node metrics and edge streams are operating within configured tolerances.'}
                </p>
                <div className="pt-2">
                  <button
                    onClick={() => testTriggerRule(rules[0]?.id || '')}
                    className="px-3 py-1.5 bg-[#F1F5F9] dark:bg-[#1E293B] hover:bg-slate-200 dark:hover:bg-[#334155] text-amber-700 dark:text-[#FFC107] rounded-lg text-xs font-mono font-bold transition-colors cursor-pointer"
                  >
                    Simulate Test Alarm
                  </button>
                </div>
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-3">
                {displayedAlarms.map((alarm) => {
                  const isRelevant = alarm.targetRoles.includes(currentUser.role);

                  return (
                    <div
                      key={alarm.id}
                      className={`p-3.5 rounded-xl border transition-all ${
                        alarm.status === 'ACTIVE_UNACK'
                          ? alarm.severity === 'CRITICAL'
                            ? 'bg-rose-50 dark:bg-rose-950/20 border-rose-200 dark:border-rose-500/50 shadow-sm dark:shadow-md dark:shadow-rose-950/30'
                            : 'bg-white dark:bg-[#111114] border-amber-300 dark:border-amber-500/40'
                          : alarm.status === 'RESOLVED'
                          ? 'bg-[#F8FAFC] dark:bg-[#0B0B0C] border-[#E2E8F0] dark:border-[#1E293B] opacity-75'
                          : 'bg-white dark:bg-[#111114] border-[#E2E8F0] dark:border-[#1E293B]'
                      }`}
                    >
                      <div className="flex flex-wrap items-start justify-between gap-2.5 mb-2">
                        <div className="flex items-center gap-2 min-w-0">
                          {/* Severity Badge */}
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold border uppercase tracking-wider ${getSeverityBadge(
                              alarm.severity
                            )}`}
                          >
                            {alarm.severity}
                          </span>

                          {/* Status Badge */}
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold border ${getStatusBadge(
                              alarm.status
                            )}`}
                          >
                            {alarm.status.replace('_', ' ')}
                          </span>

                          {/* Title */}
                          <h3 className="font-bold text-xs sm:text-sm text-[#0F172A] dark:text-[#F8FAFC] truncate">
                            {alarm.ruleName}
                          </h3>
                        </div>

                        {/* Triggered Timestamp & Actions */}
                        <div className="flex items-center gap-2">
                          <span className="text-[10px] text-[#64748B] font-mono flex items-center gap-1 tabular-nums">
                            <Clock className="w-3 h-3" />
                            {new Date(alarm.triggeredAt).toLocaleTimeString()}
                          </span>

                          {/* Acknowledge Button */}
                          {alarm.status === 'ACTIVE_UNACK' && (
                            <button
                              onClick={() => setAcknowledgingAlarm(alarm)}
                              className="px-2.5 py-1 bg-emerald-50 dark:bg-emerald-600/20 hover:bg-emerald-100 dark:hover:bg-emerald-600/30 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-500/40 rounded text-xs font-mono font-bold transition-colors cursor-pointer flex items-center gap-1"
                            >
                              <CheckCircle2 className="w-3.5 h-3.5" />
                              <span>Acknowledge</span>
                            </button>
                          )}

                          {/* Resolve Button */}
                          {alarm.status !== 'RESOLVED' && (
                            <button
                              onClick={() => setResolvingAlarm(alarm)}
                              className="px-2.5 py-1 bg-[#F1F5F9] dark:bg-[#1E293B] hover:bg-slate-200 dark:hover:bg-[#334155] text-[#475569] dark:text-[#94A3B8] hover:text-[#0F172A] dark:hover:text-[#F8FAFC] border border-[#CBD5E1] dark:border-[#334155] rounded text-xs font-mono transition-colors cursor-pointer"
                            >
                              Resolve
                            </button>
                          )}
                        </div>
                      </div>

                      {/* Condition Description & Topic */}
                      <div className="grid grid-cols-1 md:grid-cols-12 gap-2 text-xs py-2 bg-[#F8FAFC] dark:bg-[#0B0B0C] rounded-lg p-2.5 border border-[#E2E8F0] dark:border-[#1E293B] my-2">
                        <div className="md:col-span-8 space-y-1">
                          <div className="flex items-center gap-2 text-[11px] font-mono text-amber-700 dark:text-[#FFC107]">
                            <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                            <span className="font-semibold">{alarm.conditionDescription}</span>
                          </div>
                          <div className="text-[10px] text-[#64748B] dark:text-[#94A3B8] font-mono truncate flex items-center gap-1">
                            <span className="text-[#64748B]">TOPIC:</span>
                            <span className="text-[#0F172A] dark:text-[#F8FAFC]">{alarm.topic}</span>
                          </div>
                        </div>

                        {/* Telemetry Snapshot & Value */}
                        <div className="md:col-span-4 flex items-center justify-between md:justify-end gap-3 text-right">
                          <div>
                            <div className="text-[9px] text-[#64748B] uppercase font-mono">Live Breached Value</div>
                            <div className="text-sm font-mono font-bold text-rose-600 dark:text-rose-400 tabular-nums">
                              {String(alarm.currentValue)} {alarm.unit || ''}
                            </div>
                          </div>

                          {/* Jump to Node In UNS Tree */}
                          <button
                            onClick={() => jumpToTopicInTree(alarm.topic)}
                            className="p-1.5 rounded bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] hover:border-amber-500 dark:hover:border-[#FFC107] text-[#64748B] dark:text-[#94A3B8] hover:text-amber-700 dark:hover:text-[#FFC107] transition-colors cursor-pointer"
                            title="Inspect in UNS Hierarchy Tree"
                          >
                            <ExternalLink className="w-3.5 h-3.5" />
                          </button>

                          {/* Jump to Historian Trend */}
                          <button
                            onClick={() => jumpToHistorian(alarm.topic)}
                            className="p-1.5 rounded bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] hover:border-amber-500 dark:hover:border-[#FFC107] text-[#64748B] dark:text-[#94A3B8] hover:text-amber-700 dark:hover:text-[#FFC107] transition-colors cursor-pointer"
                            title="View Historical Trend Graph"
                          >
                            <TrendingUp className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>

                      {/* Footer: Target Roles & Operator Notes */}
                      <div className="flex flex-wrap items-center justify-between gap-2 text-[10px] text-[#64748B]">
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <span className="font-mono text-[#64748B]">Target Roles:</span>
                          {alarm.targetRoles.map((role) => {
                            const roleCfg = ROLE_CONFIGS[role] || ROLE_CONFIGS.viewer;
                            const isMy = role === currentUser.role;
                            return (
                              <span
                                key={role}
                                className={`px-1.5 py-0.2 rounded font-mono font-bold border ${roleCfg.badgeBg} ${roleCfg.badgeText} ${roleCfg.badgeBorder} ${
                                  isMy ? 'ring-1 ring-amber-500 dark:ring-[#FFC107]' : ''
                                }`}
                              >
                                {roleCfg.label} {isMy ? '(You)' : ''}
                              </span>
                            );
                          })}
                        </div>

                        {alarm.acknowledgedBy && (
                          <div className="font-mono text-emerald-600 dark:text-emerald-400 flex items-center gap-1">
                            <CheckCircle2 className="w-3 h-3" />
                            <span>Ack: {alarm.acknowledgedBy}</span>
                          </div>
                        )}
                      </div>

                      {alarm.notes && (
                        <div className="mt-1.5 pt-1.5 border-t border-[#E2E8F0] dark:border-[#1E293B] text-[11px] text-[#64748B] dark:text-[#94A3B8] italic">
                          "{alarm.notes}"
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {activeSubTab === 'rules' && (
          <div className="space-y-4">
            {/* Rules Header & Create Action */}
            <div className="bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] rounded-lg p-3 flex items-center justify-between">
              <div>
                <h2 className="font-display font-bold text-sm text-[#0F172A] dark:text-[#F8FAFC] text-balance">Configured Alert Rules</h2>
                <p className="text-[11px] text-[#64748B] dark:text-[#94A3B8] text-pretty">
                  Define telemetry thresholds, evaluation conditions, and the predefined roles that receive alerts.
                </p>
              </div>
              <div className="flex items-center gap-2">
                {/* Whether these rules reach the next shift, or stop at this browser. */}
                {rulesOrigin === 'SERVER' ? (
                  <span
                    title="Stored in the platform database — every console at this site sees these rules"
                    className="px-2 py-1 rounded-md bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-500/30 font-mono text-[10px] uppercase flex items-center gap-1"
                  >
                    <Database className="w-3 h-3" />
                    Platform
                  </span>
                ) : (
                  <span
                    title="These rules exist only in this browser. Other consoles will not evaluate them."
                    className="px-2 py-1 rounded-md bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-400 border border-amber-200 dark:border-amber-500/30 font-mono text-[10px] uppercase flex items-center gap-1"
                  >
                    <MonitorSmartphone className="w-3 h-3" />
                    This Browser
                  </span>
                )}
                <button
                  onClick={() => void refreshRules()}
                  title="Reload the rules the platform holds"
                  className="p-1.5 rounded-lg border border-[#E2E8F0] dark:border-[#1E293B] text-[#64748B] dark:text-[#94A3B8] hover:text-[#0F172A] dark:hover:text-[#F8FAFC] transition-colors cursor-pointer"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                </button>
                <button
                  onClick={handleOpenCreateRule}
                  className="px-3 py-1.5 bg-amber-500 dark:bg-[#FFC107] hover:bg-amber-400 dark:hover:bg-[#FFB300] text-[#0B0B0C] font-bold rounded-lg text-xs font-mono transition-colors cursor-pointer flex items-center gap-1.5"
                >
                  <Plus className="w-4 h-4" />
                  <span>Add Rule</span>
                </button>
              </div>
            </div>

            {rulesError && (
              <div className="bg-amber-50 dark:bg-amber-500/10 border border-amber-200 dark:border-amber-500/30 rounded-lg p-3 flex items-start gap-2">
                <AlertTriangle className="w-4 h-4 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
                <p className="text-[11px] text-amber-800 dark:text-amber-300 text-pretty font-mono">{rulesError}</p>
              </div>
            )}

            {/* Rules Table */}
            <div className="bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] rounded-xl overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse text-xs">
                  <thead>
                    <tr className="border-b border-[#E2E8F0] dark:border-[#1E293B] bg-[#F8FAFC] dark:bg-[#0B0B0C] text-[#64748B] font-mono text-[10px] uppercase">
                      <th className="py-2.5 px-3">Status</th>
                      <th className="py-2.5 px-3">Rule Name &amp; Target Topic</th>
                      <th className="py-2.5 px-3">Condition &amp; Threshold</th>
                      <th className="py-2.5 px-3">Severity</th>
                      <th className="py-2.5 px-3">Triggered Roles</th>
                      <th className="py-2.5 px-3 text-center">Triggers</th>
                      <th className="py-2.5 px-3 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#E2E8F0] dark:divide-[#1E293B]/60 font-mono text-[11px]">
                    {rules.map((rule) => (
                      <tr key={rule.id} className="hover:bg-slate-50 dark:hover:bg-[#1E293B]/20 transition-colors">
                        {/* Toggle Enabled */}
                        <td className="py-3 px-3">
                          <button
                            onClick={() => toggleRuleEnabled(rule.id, !rule.enabled)}
                            className={`w-9 h-5 rounded-full p-0.5 transition-colors cursor-pointer flex items-center ${
                              rule.enabled ? 'bg-emerald-500 justify-end' : 'bg-[#CBD5E1] dark:bg-[#1E293B] justify-start'
                            }`}
                            title={rule.enabled ? 'Disable Rule' : 'Enable Rule'}
                          >
                            <span className="w-4 h-4 rounded-full bg-white shadow-sm block" />
                          </button>
                        </td>

                        {/* Name & Topic */}
                        <td className="py-3 px-3 min-w-[220px]">
                          <div className="font-bold text-[#0F172A] dark:text-[#F8FAFC]">{rule.name}</div>
                          <div className="text-[10px] text-[#64748B] dark:text-[#94A3B8] truncate max-w-xs">{rule.topic}</div>
                        </td>

                        {/* Condition & Threshold */}
                        <td className="py-3 px-3">
                          <span className="px-2 py-0.5 rounded bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#E2E8F0] dark:border-[#1E293B] text-amber-700 dark:text-[#FFC107] font-semibold">
                            {rule.metricField} {rule.condition.replace('_', ' ')} {String(rule.thresholdValue)} {rule.unit || ''}
                          </span>
                        </td>

                        {/* Severity */}
                        <td className="py-3 px-3">
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-bold border ${getSeverityBadge(
                              rule.severity
                            )}`}
                          >
                            {rule.severity}
                          </span>
                        </td>

                        {/* Target Roles */}
                        <td className="py-3 px-3">
                          <div className="flex flex-wrap gap-1">
                            {rule.targetRoles.map((role) => (
                              <span
                                key={role}
                                className="px-1.5 py-0.2 rounded bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#E2E8F0] dark:border-[#1E293B] text-[9px] text-[#64748B] dark:text-[#94A3B8]"
                              >
                                {role}
                              </span>
                            ))}
                          </div>
                        </td>

                        {/* Triggers Count */}
                        <td className="py-3 px-3 text-center text-[#0F172A] dark:text-[#F8FAFC] font-bold tabular-nums">
                          {rule.triggerCount}
                        </td>

                        {/* Actions */}
                        <td className="py-3 px-3 text-right">
                          <div className="flex items-center justify-end gap-1.5">
                            <button
                              onClick={() => testTriggerRule(rule.id)}
                              className="px-2 py-1 bg-[#F1F5F9] dark:bg-[#1E293B] hover:bg-slate-200 dark:hover:bg-[#334155] text-amber-700 dark:text-[#FFC107] rounded text-[10px] transition-colors cursor-pointer"
                              title="Simulate / Test Trigger"
                            >
                              Test
                            </button>
                            <button
                              onClick={() => handleOpenEditRule(rule)}
                              className="px-2 py-1 bg-[#F1F5F9] dark:bg-[#1E293B] hover:bg-slate-200 dark:hover:bg-[#334155] text-[#475569] dark:text-[#94A3B8] hover:text-[#0F172A] dark:hover:text-[#F8FAFC] rounded text-[10px] transition-colors cursor-pointer"
                            >
                              Edit
                            </button>
                            <button
                              onClick={() => deleteRule(rule.id)}
                              className="px-2 py-1 bg-[#F1F5F9] dark:bg-[#1E293B] hover:bg-rose-50 dark:hover:bg-rose-950/40 text-[#64748B] hover:text-rose-600 dark:hover:text-rose-400 rounded text-[10px] transition-colors cursor-pointer"
                            >
                              Delete
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {activeSubTab === 'matrix' && <RoleAlertMatrix />}

        {activeSubTab === 'audit' && <AlarmAuditLog />}
      </div>

      {/* Alert Rule Editor Modal */}
      {isRuleModalOpen && (
        <AlertRuleEditorModal
          rule={editingRule}
          onClose={() => setIsRuleModalOpen(false)}
        />
      )}

      {/* Acknowledge Dialog */}
      {acknowledgingAlarm && (
        <div className="fixed inset-0 z-50 bg-black/40 dark:bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] rounded-xl max-w-md w-full p-4 space-y-3 font-sans shadow-2xl">
            <div className="flex items-center justify-between border-b border-[#E2E8F0] dark:border-[#1E293B] pb-2.5">
              <div className="flex items-center gap-2">
                <CheckCircle2 className="w-5 h-5 text-emerald-500 dark:text-emerald-400" />
                <h3 className="font-bold text-sm text-[#0F172A] dark:text-[#F8FAFC]">Acknowledge Incident</h3>
              </div>
              <button
                onClick={() => setAcknowledgingAlarm(null)}
                className="text-[#64748B] hover:text-[#0F172A] dark:hover:text-[#F8FAFC] cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="space-y-2 text-xs">
              <div className="p-2 rounded bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#E2E8F0] dark:border-[#1E293B] space-y-1">
                <div className="font-bold text-amber-700 dark:text-[#FFC107]">{acknowledgingAlarm.ruleName}</div>
                <div className="text-[11px] text-[#64748B] dark:text-[#94A3B8] font-mono">{acknowledgingAlarm.conditionDescription}</div>
                <div className="text-[10px] text-[#64748B] font-mono">{acknowledgingAlarm.topic}</div>
              </div>

              <div>
                <label className="block text-[11px] font-medium text-[#64748B] dark:text-[#94A3B8] mb-1">
                  Operator Action Notes (Optional):
                </label>
                <textarea
                  value={ackNotes}
                  onChange={(e) => setAckNotes(e.target.value)}
                  placeholder="e.g., Investigating cooling valve bypass on Line 1. Dispatching tech."
                  rows={3}
                  className="w-full bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#CBD5E1] dark:border-[#1E293B] rounded-lg p-2 text-xs text-[#0F172A] dark:text-[#F8FAFC] focus:outline-none focus:border-amber-500 dark:focus:border-[#FFC107] font-sans"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-[#E2E8F0] dark:border-[#1E293B]">
              <button
                onClick={() => setAcknowledgingAlarm(null)}
                className="px-3 py-1.5 rounded-lg border border-[#CBD5E1] dark:border-[#1E293B] text-[#64748B] dark:text-[#94A3B8] hover:text-[#0F172A] dark:hover:text-[#F8FAFC] text-xs font-mono cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmAck}
                className="px-4 py-1.5 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-black font-bold text-xs font-mono cursor-pointer shadow-sm"
              >
                Confirm Acknowledge
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Resolve Dialog */}
      {resolvingAlarm && (
        <div className="fixed inset-0 z-50 bg-black/40 dark:bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] rounded-xl max-w-md w-full p-4 space-y-3 font-sans shadow-2xl">
            <div className="flex items-center justify-between border-b border-[#E2E8F0] dark:border-[#1E293B] pb-2.5">
              <div className="flex items-center gap-2">
                <CheckCheck className="w-5 h-5 text-emerald-500 dark:text-emerald-400" />
                <h3 className="font-bold text-sm text-[#0F172A] dark:text-[#F8FAFC]">Resolve Incident</h3>
              </div>
              <button
                onClick={() => setResolvingAlarm(null)}
                className="text-[#64748B] hover:text-[#0F172A] dark:hover:text-[#F8FAFC] cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="space-y-2 text-xs">
              <div className="p-2 rounded bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#E2E8F0] dark:border-[#1E293B]">
                <div className="font-bold text-[#0F172A] dark:text-[#F8FAFC]">{resolvingAlarm.ruleName}</div>
                <div className="text-[10px] text-[#64748B] font-mono">{resolvingAlarm.topic}</div>
              </div>

              <div>
                <label className="block text-[11px] font-medium text-[#64748B] dark:text-[#94A3B8] mb-1">
                  Resolution Root Cause &amp; Summary:
                </label>
                <textarea
                  value={resolveNotes}
                  onChange={(e) => setResolveNotes(e.target.value)}
                  placeholder="e.g., Replaced failed thermocouple sensor T-402. Calibrated and verified nominal 72°C reading."
                  rows={3}
                  className="w-full bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#CBD5E1] dark:border-[#1E293B] rounded-lg p-2 text-xs text-[#0F172A] dark:text-[#F8FAFC] focus:outline-none focus:border-amber-500 dark:focus:border-[#FFC107] font-sans"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-[#E2E8F0] dark:border-[#1E293B]">
              <button
                onClick={() => setResolvingAlarm(null)}
                className="px-3 py-1.5 rounded-lg border border-[#CBD5E1] dark:border-[#1E293B] text-[#64748B] dark:text-[#94A3B8] hover:text-[#0F172A] dark:hover:text-[#F8FAFC] text-xs font-mono cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmResolve}
                className="px-4 py-1.5 rounded-lg bg-amber-500 dark:bg-[#FFC107] hover:bg-amber-400 dark:hover:bg-[#FFB300] text-[#0B0B0C] font-bold text-xs font-mono cursor-pointer"
              >
                Mark Resolved
              </button>
            </div>
          </div>
        </div>
      )}
    </PageShell>
  );
};

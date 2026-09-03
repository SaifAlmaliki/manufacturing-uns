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
  consoleTokens,
} from '../ui/console-ui';

type AlarmSubTab = 'active' | 'rules' | 'matrix' | 'audit';

function AlarmPanel({
  icon,
  title,
  description,
  variant = 'default',
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  variant?: 'default' | 'offline' | 'success';
}) {
  const variantClass =
    variant === 'offline'
      ? 'border-rose-500/30 bg-rose-500/5'
      : variant === 'success'
        ? 'border-emerald-500/20 bg-emerald-500/5'
        : '';

  return (
    <ConsoleCard
      padding="lg"
      className={`flex min-h-[min(420px,calc(100dvh-12rem))] w-full flex-col items-center justify-center gap-3 text-center ${variantClass}`}
    >
      {icon}
      <div className="max-w-2xl space-y-2">
        <h3 className="text-lg font-semibold text-white">{title}</h3>
        <p className="text-sm text-zinc-400 text-pretty">{description}</p>
      </div>
    </ConsoleCard>
  );
}

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
    toggleRuleEnabled,
    deleteRule,
    clearResolvedAlarms,
    rulesOrigin,
    rulesError,
    rulesLoading,
    canPersistRules,
    isPlatformLive,
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
    if (!canPersistRules) return;
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
      <div className="min-h-0 flex-1 overflow-y-auto">
        <PageContent fullWidth className="flex min-h-full flex-col gap-3 pb-4">
          {/* Toolbar: compact KPIs + actions — page title lives in the app header */}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <PageStat compact label="Critical" value={criticalAlarmsCount} valueClassName={criticalAlarmsCount > 0 ? 'text-red-400' : 'text-white'} icon={<AlertTriangle className="size-3.5 text-red-400" />} iconBg="bg-red-500/15" />
              <PageStat compact label="My Pending" value={myUnacknowledgedCount} valueClassName={myUnacknowledgedCount > 0 ? 'text-[#FF7A00]' : 'text-white'} icon={<UserCheck className="size-3.5 text-[#FF7A00]" />} />
              <PageStat compact label="Plant Active" value={activeAlarms.filter((a) => a.status !== 'RESOLVED').length} icon={<Bell className="size-3.5 text-zinc-400" />} iconBg="bg-zinc-800" />
              <PageStat compact label="Rules" value={`${rules.filter((r) => r.enabled).length}/${rules.length}`} valueClassName="text-emerald-400" icon={<Sliders className="size-3.5 text-emerald-400" />} iconBg="bg-emerald-500/15" />
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              <BtnGhost onClick={toggleAudioMute} title={isMuted ? 'Unmute' : 'Mute audio'} className="px-2.5 py-1.5 text-xs">
                {isMuted ? <VolumeX className="size-3.5 text-red-400" /> : <Volume2 className="size-3.5 text-[#FF7A00]" />}
                <span className="hidden sm:inline">{isMuted ? 'Muted' : 'Audio'}</span>
              </BtnGhost>
              {myUnacknowledgedCount > 0 && (
                <BtnSecondary id="bulk-ack-alarms-btn" onClick={() => bulkAcknowledgeAll()} className="px-2.5 py-1.5 text-xs">
                  <CheckCheck className="size-3.5" />
                  Ack ({myUnacknowledgedCount})
                </BtnSecondary>
              )}
              <BtnPrimary
                id="create-alert-rule-btn"
                onClick={handleOpenCreateRule}
                disabled={!canPersistRules}
                className="px-2.5 py-1.5 text-xs"
                title={
                  canPersistRules
                    ? 'Create a new alert rule in Postgres'
                    : 'Start the GraphQL backend (port 8000) to create alert rules'
                }
              >
                <Plus className="size-3.5" />
                New Rule
              </BtnPrimary>
            </div>
          </div>

        <SegmentTabs tabs={alarmTabs} active={activeSubTab} onChange={(id) => setActiveSubTab(id as AlarmSubTab)} />

        {!isPlatformLive && !rulesLoading && (
          <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
            Platform offline — no alarm data until GraphQL on port 8000 is reachable.
          </div>
        )}

        <div className="min-h-0 flex-1">
        {activeSubTab === 'active' && (
          <div className="flex h-full flex-col gap-2">
            {/* Role tabs + search + severity — one toolbar row */}
            <div className="flex flex-wrap items-center gap-1 rounded-xl border border-zinc-800 bg-zinc-900/60 p-1">
              {(
                [
                  { id: 'my_role' as const, label: `My Role (${currentUser.role})` },
                  { id: 'all' as const, label: `All (${activeAlarms.length})` },
                ] as const
              ).map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setRoleFilter(tab.id)}
                  className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                    roleFilter === tab.id ? consoleTokens.tabActive : consoleTokens.tabInactive
                  }`}
                >
                  {tab.label}
                </button>
              ))}
              <div className="mx-0.5 hidden h-7 w-px shrink-0 bg-zinc-700 sm:block" aria-hidden />
              <div className="relative min-w-[140px] flex-1 px-0.5">
                <Search className="pointer-events-none absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-zinc-500" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search alarms…"
                  className="w-full rounded-lg border-0 bg-zinc-800/60 py-1.5 pl-8 pr-2 text-sm text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:ring-1 focus:ring-[#FF7A00]/40"
                />
              </div>
              <select
                value={severityFilter}
                onChange={(e) => setSeverityFilter(e.target.value)}
                className="shrink-0 rounded-lg border-0 bg-zinc-800/60 px-2.5 py-1.5 text-sm text-zinc-300 focus:outline-none focus:ring-1 focus:ring-[#FF7A00]/40"
              >
                <option value="ALL">All severities</option>
                <option value="CRITICAL">Critical</option>
                <option value="HIGH">High</option>
                <option value="WARNING">Warning</option>
                <option value="INFO">Info</option>
              </select>
            </div>

            {/* Alarms List */}
            {!isPlatformLive ? (
              <AlarmPanel
                variant="offline"
                icon={<AlertTriangle className="size-14 text-rose-400 opacity-90" />}
                title="Platform offline"
                description={
                  rulesError ??
                  'Active incidents require a live GraphQL connection and MQTT feed. Start the backend stack, then refresh this page.'
                }
              />
            ) : displayedAlarms.length === 0 ? (
              <AlarmPanel
                variant="success"
                icon={<CheckCircle2 className="size-14 text-emerald-400 opacity-80" />}
                title="No active incidents"
                description={
                  roleFilter === 'my_role'
                    ? `No live alarms are routed to role '${currentUser.role}'.`
                    : 'No configured alert rules have been breached on the live MQTT feed.'
                }
              />
            ) : (
              <div className="grid gap-4 xl:grid-cols-2">
                {displayedAlarms.map((alarm) => {
                  const severityColor =
                    alarm.severity === 'CRITICAL'
                      ? 'bg-red-500'
                      : alarm.severity === 'HIGH'
                        ? 'bg-[#FF7A00]'
                        : alarm.severity === 'WARNING'
                          ? 'bg-yellow-500'
                          : 'bg-zinc-500';

                  return (
                    <ConsoleCard key={alarm.id} padding="lg" className="flex flex-col gap-4">
                      <div className="flex flex-wrap items-start justify-between gap-4">
                        <div className="flex min-w-0 flex-1 items-start gap-4">
                          <span className={`mt-2 size-3 shrink-0 rounded-full ${severityColor}`} />
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <h3 className="text-base font-semibold text-white">{alarm.ruleName}</h3>
                              <span className={`rounded-md border px-2 py-0.5 text-[10px] font-bold uppercase ${getStatusBadge(alarm.status)}`}>
                                {alarm.status.replace('_', ' ')}
                              </span>
                            </div>
                            <p className="mt-1 text-sm text-zinc-300">{alarm.conditionDescription}</p>
                            <p className="mt-2 break-all font-mono text-xs text-zinc-500">{alarm.topic}</p>
                          </div>
                        </div>
                        <div className="shrink-0 text-right">
                          <div className="text-2xl font-semibold tabular-nums text-[#FF7A00]">
                            {String(alarm.currentValue)} {alarm.unit || ''}
                          </div>
                          <div className="mt-1 text-xs text-zinc-500">
                            {new Date(alarm.triggeredAt).toLocaleString()}
                          </div>
                        </div>
                      </div>

                      <div className="flex flex-wrap items-center gap-2 border-t border-zinc-800 pt-4">
                        {alarm.status === 'ACTIVE_UNACK' && (
                          <BtnPrimary onClick={() => setAcknowledgingAlarm(alarm)} className="py-1.5 text-xs">
                            <CheckCircle2 className="size-3.5" />
                            Acknowledge
                          </BtnPrimary>
                        )}
                        {alarm.status !== 'RESOLVED' && (
                          <BtnSecondary onClick={() => setResolvingAlarm(alarm)} className="py-1.5 text-xs">
                            Resolve
                          </BtnSecondary>
                        )}
                        <BtnGhost onClick={() => jumpToTopicInTree(alarm.topic)} className="py-1.5 text-xs">
                          <ExternalLink className="size-3.5" />
                          Tree
                        </BtnGhost>
                        <BtnGhost onClick={() => jumpToHistorian(alarm.topic)} className="py-1.5 text-xs">
                          <TrendingUp className="size-3.5" />
                          Historian
                        </BtnGhost>
                        {alarm.acknowledgedBy && (
                          <span className="ml-auto text-xs text-emerald-400">Ack: {alarm.acknowledgedBy}</span>
                        )}
                      </div>
                    </ConsoleCard>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {activeSubTab === 'rules' && (
          <div className="space-y-2">
            {!canPersistRules && (
              <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
                {rulesError ?? 'Platform offline — rules are stored in Postgres via GraphQL.'}
              </div>
            )}
            <div className="flex flex-wrap items-center justify-end gap-2">
              {rulesOrigin === 'SERVER' ? (
                <span className="flex items-center gap-1 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 font-mono text-[10px] uppercase text-emerald-400">
                  <Database className="size-3.5" />
                  Platform
                </span>
              ) : (
                <span className="flex items-center gap-1 rounded-lg border border-amber-500/30 bg-amber-500/10 px-2 py-1 font-mono text-[10px] uppercase text-amber-400">
                  <MonitorSmartphone className="size-3.5" />
                  Offline
                </span>
              )}
              <BtnGhost onClick={() => void refreshRules()} title="Reload rules" className="px-2 py-1.5">
                <RefreshCw className="size-3.5" />
              </BtnGhost>
              <BtnPrimary onClick={handleOpenCreateRule} disabled={!canPersistRules} className="px-2.5 py-1.5 text-xs">
                <Plus className="size-3.5" />
                Add Rule
              </BtnPrimary>
            </div>

            {rulesError && canPersistRules && (
              <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200 font-mono">
                {rulesError}
              </div>
            )}

            <ConsoleCard padding="none" className="overflow-hidden">
              {rulesLoading ? (
                <div className="p-16 text-center font-mono text-sm text-zinc-500">Loading alert rules from platform…</div>
              ) : rules.length === 0 ? (
                <AlarmPanel
                  icon={<Sliders className="size-14 text-zinc-500 opacity-60" />}
                  title="No alert rules configured"
                  description={
                    canPersistRules
                      ? 'Create your first rule — it will be stored in the console.alert_rules Postgres table.'
                      : 'Connect to the GraphQL backend to load and manage rules.'
                  }
                />
              ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[960px] text-left border-collapse text-sm">
                  <thead>
                    <tr className="border-b border-zinc-800 bg-zinc-900/80 font-mono text-[11px] uppercase text-zinc-500">
                      <th className="px-4 py-3">Status</th>
                      <th className="px-4 py-3">Rule Name &amp; Target Topic</th>
                      <th className="px-4 py-3">Condition &amp; Threshold</th>
                      <th className="px-4 py-3">Severity</th>
                      <th className="px-4 py-3">Triggered Roles</th>
                      <th className="px-4 py-3 text-center">Triggers</th>
                      <th className="px-4 py-3 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-800/80 font-mono text-xs">
                    {rules.map((rule) => (
                      <tr key={rule.id} className="transition-colors hover:bg-zinc-800/30">
                        <td className="px-4 py-4">
                          <button
                            onClick={() => toggleRuleEnabled(rule.id, !rule.enabled)}
                            className={`flex h-5 w-9 cursor-pointer items-center rounded-full p-0.5 transition-colors ${
                              rule.enabled ? 'justify-end bg-emerald-500' : 'justify-start bg-zinc-700'
                            }`}
                            title={rule.enabled ? 'Disable Rule' : 'Enable Rule'}
                          >
                            <span className="block size-4 rounded-full bg-white shadow-sm" />
                          </button>
                        </td>
                        <td className="min-w-[280px] px-4 py-4">
                          <div className="font-semibold text-white">{rule.name}</div>
                          <div className="mt-1 max-w-md truncate text-xs text-zinc-500">{rule.topic}</div>
                        </td>
                        <td className="px-4 py-4">
                          <span className="rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 font-semibold text-[#FF7A00]">
                            {rule.metricField} {rule.condition.replace('_', ' ')} {String(rule.thresholdValue)} {rule.unit || ''}
                          </span>
                        </td>
                        <td className="px-4 py-4">
                          <span className={`rounded border px-2 py-0.5 text-[10px] font-bold ${getSeverityBadge(rule.severity)}`}>
                            {rule.severity}
                          </span>
                        </td>
                        <td className="px-4 py-4">
                          <div className="flex flex-wrap gap-1">
                            {rule.targetRoles.map((role) => (
                              <span
                                key={role}
                                className="rounded border border-zinc-700 bg-zinc-900 px-1.5 py-0.5 text-[10px] text-zinc-400"
                              >
                                {role}
                              </span>
                            ))}
                          </div>
                        </td>
                        <td className="px-4 py-4 text-center font-bold tabular-nums text-white">
                          {rule.triggerCount}
                        </td>
                        <td className="px-4 py-4 text-right">
                          <div className="flex items-center justify-end gap-2">
                            <BtnSecondary onClick={() => handleOpenEditRule(rule)} className="px-2.5 py-1 text-xs">
                              Edit
                            </BtnSecondary>
                            <BtnGhost
                              onClick={() => deleteRule(rule.id)}
                              className="px-2.5 py-1 text-xs text-rose-400 hover:text-rose-300"
                            >
                              Delete
                            </BtnGhost>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              )}
            </ConsoleCard>
          </div>
        )}

        {activeSubTab === 'matrix' && <RoleAlertMatrix />}

        {activeSubTab === 'audit' && <AlarmAuditLog />}
        </div>
        </PageContent>
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

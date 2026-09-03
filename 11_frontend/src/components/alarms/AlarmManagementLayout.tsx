import React, { useMemo, useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import {
  AlertTriangle,
  Bell,
  CheckCheck,
  CheckCircle2,
  Clock,
  Plus,
  Shield,
  Sliders,
  UserCheck,
  Volume2,
  VolumeX,
  X,
} from 'lucide-react';
import { useAlarms } from '../../context/AlarmContext';
import { ActiveAlarm, AlertRule } from '../../types/alarm';
import { AlertRuleEditorModal } from './AlertRuleEditorModal';
import {
  CompactKpiRow,
  PageShell,
  PageContent,
  PageStat,
  SegmentTabs,
  BtnPrimary,
  BtnSecondary,
  BtnGhost,
} from '../ui/console-ui';
import type { AlarmOutletContext } from './alarmUi';

export const ALERT_TAB_PATHS = {
  active: '/alerts/active',
  rules: '/alerts/rules',
  matrix: '/alerts/matrix',
  audit: '/alerts/audit',
} as const;

export type AlertTabId = keyof typeof ALERT_TAB_PATHS;

function tabIdFromPath(pathname: string): AlertTabId {
  const segment = pathname.replace(/^\/alerts\/?/, '').split('/')[0];
  if (segment === 'rules' || segment === 'matrix' || segment === 'audit') return segment;
  return 'active';
}

export const AlarmManagementLayout: React.FC = () => {
  const location = useLocation();
  const activeSubTab = useMemo(() => tabIdFromPath(location.pathname), [location.pathname]);

  const {
    rules,
    activeAlarms,
    myUnacknowledgedCount,
    criticalAlarmsCount,
    isMuted,
    toggleAudioMute,
    bulkAcknowledgeAll,
    acknowledgeAlarm,
    resolveAlarm,
    canPersistRules,
    isPlatformLive,
    rulesLoading,
  } = useAlarms();

  const [editingRule, setEditingRule] = useState<AlertRule | null>(null);
  const [isRuleModalOpen, setIsRuleModalOpen] = useState(false);
  const [acknowledgingAlarm, setAcknowledgingAlarm] = useState<ActiveAlarm | null>(null);
  const [ackNotes, setAckNotes] = useState('');
  const [resolvingAlarm, setResolvingAlarm] = useState<ActiveAlarm | null>(null);
  const [resolveNotes, setResolveNotes] = useState('');

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
    {
      id: 'active',
      label: 'Active Incidents',
      icon: Bell,
      badge: myUnacknowledgedCount || undefined,
      href: ALERT_TAB_PATHS.active,
    },
    {
      id: 'rules',
      label: 'Alert Rules',
      icon: Sliders,
      badge: rules.length,
      href: ALERT_TAB_PATHS.rules,
    },
    { id: 'matrix', label: 'Role Matrix', icon: Shield, href: ALERT_TAB_PATHS.matrix },
    { id: 'audit', label: 'Audit Trail', icon: Clock, href: ALERT_TAB_PATHS.audit },
  ];

  const outletContext: AlarmOutletContext = {
    onOpenCreateRule: handleOpenCreateRule,
    onOpenEditRule: handleOpenEditRule,
    onAcknowledge: setAcknowledgingAlarm,
    onResolve: setResolvingAlarm,
  };

  return (
    <PageShell id="alarm-management-view" scroll={false} className="flex flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <PageContent fullWidth className="flex min-h-full flex-col gap-3 pb-4">
          <CompactKpiRow
            actions={
              <>
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
              </>
            }
          >
            <PageStat compact label="Critical" value={criticalAlarmsCount} valueClassName={criticalAlarmsCount > 0 ? 'text-red-400' : 'text-white'} icon={<AlertTriangle className="size-3.5 text-red-400" />} iconBg="bg-red-500/15" />
            <PageStat compact label="My Pending" value={myUnacknowledgedCount} valueClassName={myUnacknowledgedCount > 0 ? 'text-[#FF7A00]' : 'text-white'} icon={<UserCheck className="size-3.5 text-[#FF7A00]" />} />
            <PageStat compact label="Plant Active" value={activeAlarms.filter((a) => a.status !== 'RESOLVED').length} icon={<Bell className="size-3.5 text-zinc-400" />} iconBg="bg-zinc-800" />
            <PageStat compact label="Rules" value={`${rules.filter((r) => r.enabled).length}/${rules.length}`} valueClassName="text-emerald-400" icon={<Sliders className="size-3.5 text-emerald-400" />} iconBg="bg-emerald-500/15" />
          </CompactKpiRow>

          <SegmentTabs tabs={alarmTabs} active={activeSubTab} />

          {!isPlatformLive && !rulesLoading && (
            <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              Platform offline — no alarm data until GraphQL on port 8000 is reachable.
            </div>
          )}

          <div className="min-h-0 flex-1">
            <Outlet context={outletContext} />
          </div>
        </PageContent>
      </div>

      {isRuleModalOpen && (
        <AlertRuleEditorModal rule={editingRule} onClose={() => setIsRuleModalOpen(false)} />
      )}

      {acknowledgingAlarm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md space-y-3 rounded-xl border border-zinc-800 bg-[#111114] p-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-zinc-800 pb-2.5">
              <div className="flex items-center gap-2">
                <CheckCircle2 className="size-5 text-emerald-400" />
                <h3 className="text-sm font-bold text-white">Acknowledge Incident</h3>
              </div>
              <button onClick={() => setAcknowledgingAlarm(null)} className="cursor-pointer text-zinc-500 hover:text-white">
                <X className="size-4" />
              </button>
            </div>
            <div className="space-y-2 text-xs">
              <div className="space-y-1 rounded-lg border border-zinc-800 bg-zinc-900/60 p-2">
                <div className="font-bold text-[#FF7A00]">{acknowledgingAlarm.ruleName}</div>
                <div className="font-mono text-[11px] text-zinc-400">{acknowledgingAlarm.conditionDescription}</div>
                <div className="font-mono text-[10px] text-zinc-500">{acknowledgingAlarm.topic}</div>
              </div>
              <div>
                <label className="mb-1 block text-[11px] font-medium text-zinc-500">Operator notes (optional)</label>
                <textarea
                  value={ackNotes}
                  onChange={(e) => setAckNotes(e.target.value)}
                  placeholder="e.g., Investigating cooling valve bypass on Line 1."
                  rows={3}
                  className="w-full rounded-lg border border-zinc-800 bg-zinc-900/80 p-2 text-xs text-zinc-200 focus:border-[#FF7A00]/50 focus:outline-none"
                />
              </div>
            </div>
            <div className="flex items-center justify-end gap-2 border-t border-zinc-800 pt-2">
              <BtnGhost onClick={() => setAcknowledgingAlarm(null)} className="px-3 py-1.5 text-xs">
                Cancel
              </BtnGhost>
              <BtnPrimary onClick={handleConfirmAck} className="px-4 py-1.5 text-xs">
                Confirm Acknowledge
              </BtnPrimary>
            </div>
          </div>
        </div>
      )}

      {resolvingAlarm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md space-y-3 rounded-xl border border-zinc-800 bg-[#111114] p-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-zinc-800 pb-2.5">
              <div className="flex items-center gap-2">
                <CheckCheck className="size-5 text-emerald-400" />
                <h3 className="text-sm font-bold text-white">Resolve Incident</h3>
              </div>
              <button onClick={() => setResolvingAlarm(null)} className="cursor-pointer text-zinc-500 hover:text-white">
                <X className="size-4" />
              </button>
            </div>
            <div className="space-y-2 text-xs">
              <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-2">
                <div className="font-bold text-white">{resolvingAlarm.ruleName}</div>
                <div className="font-mono text-[10px] text-zinc-500">{resolvingAlarm.topic}</div>
              </div>
              <div>
                <label className="mb-1 block text-[11px] font-medium text-zinc-500">Resolution summary</label>
                <textarea
                  value={resolveNotes}
                  onChange={(e) => setResolveNotes(e.target.value)}
                  placeholder="e.g., Replaced failed thermocouple sensor T-402."
                  rows={3}
                  className="w-full rounded-lg border border-zinc-800 bg-zinc-900/80 p-2 text-xs text-zinc-200 focus:border-[#FF7A00]/50 focus:outline-none"
                />
              </div>
            </div>
            <div className="flex items-center justify-end gap-2 border-t border-zinc-800 pt-2">
              <BtnGhost onClick={() => setResolvingAlarm(null)} className="px-3 py-1.5 text-xs">
                Cancel
              </BtnGhost>
              <BtnPrimary onClick={handleConfirmResolve} className="px-4 py-1.5 text-xs">
                Mark Resolved
              </BtnPrimary>
            </div>
          </div>
        </div>
      )}
    </PageShell>
  );
};

import React, { useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import {
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  TrendingUp,
} from 'lucide-react';
import { useAlarms } from '../../context/AlarmContext';
import { useAuth } from '../../context/AuthContext';
import { useUNS } from '../../context/UNSContext';
import {
  BtnGhost,
  BtnPrimary,
  BtnSecondary,
  ConsoleCard,
  FilterToolbar,
} from '../ui/console-ui';
import { AlarmOutletContext, AlarmPanel, getStatusBadge } from './alarmUi';

export const AlarmActiveTab: React.FC = () => {
  const { onAcknowledge, onResolve } = useOutletContext<AlarmOutletContext>();
  const { activeAlarms, myRoleAlarms, isPlatformLive, rulesError } = useAlarms();
  const { currentUser, roles } = useAuth();
  const myRole = currentUser?.role ?? roles[0] ?? 'viewer';
  const { jumpToHistorian, jumpToTopicInTree } = useUNS();

  const [roleFilter, setRoleFilter] = useState<'my_role' | 'all'>('my_role');
  const [severityFilter, setSeverityFilter] = useState<string>('ALL');
  const [searchQuery, setSearchQuery] = useState<string>('');

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

  return (
    <div className="flex h-full flex-col gap-2">
      <FilterToolbar
        tabs={{
          items: [
            { id: 'my_role', label: `My Role (${myRole})` },
            { id: 'all', label: `All (${activeAlarms.length})` },
          ],
          active: roleFilter,
          onChange: (id) => setRoleFilter(id as 'my_role' | 'all'),
        }}
        search={{
          value: searchQuery,
          onChange: setSearchQuery,
          placeholder: 'Search alarms…',
        }}
        selects={[
          {
            value: severityFilter,
            onChange: setSeverityFilter,
            'aria-label': 'Severity filter',
            options: [
              { value: 'ALL', label: 'All severities' },
              { value: 'CRITICAL', label: 'Critical' },
              { value: 'HIGH', label: 'High' },
              { value: 'WARNING', label: 'Warning' },
              { value: 'INFO', label: 'Info' },
            ],
          },
        ]}
      />

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
              ? `No live alarms are routed to role '${myRole}'.`
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
                    <BtnPrimary onClick={() => onAcknowledge(alarm)} className="py-1.5 text-xs">
                      <CheckCircle2 className="size-3.5" />
                      Acknowledge
                    </BtnPrimary>
                  )}
                  {alarm.status !== 'RESOLVED' && (
                    <BtnSecondary onClick={() => onResolve(alarm)} className="py-1.5 text-xs">
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
  );
};

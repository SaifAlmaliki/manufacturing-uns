import React from 'react';
import {
  Database,
  MonitorSmartphone,
  Plus,
  RefreshCw,
  Sliders,
} from 'lucide-react';
import { useOutletContext } from 'react-router-dom';
import { useAlarms } from '../../context/AlarmContext';
import {
  BtnGhost,
  BtnPrimary,
  BtnSecondary,
  ConsoleCard,
} from '../ui/console-ui';
import { AlarmOutletContext, AlarmPanel, getSeverityBadge } from './alarmUi';

export const AlarmRulesTab: React.FC = () => {
  const { onOpenCreateRule, onOpenEditRule } = useOutletContext<AlarmOutletContext>();
  const {
    rules,
    toggleRuleEnabled,
    deleteRule,
    rulesOrigin,
    rulesError,
    rulesLoading,
    canPersistRules,
    refreshRules,
  } = useAlarms();

  return (
    <div className="space-y-2">
      {!canPersistRules && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
          {rulesError ?? 'Platform offline — rules are stored in Postgres via GraphQL.'}
        </div>
      )}
      <div className="flex flex-wrap items-center justify-end gap-2">
        {rulesOrigin === 'SERVER' ? (
          <span className="flex items-center gap-1 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-[10px] uppercase text-emerald-400">
            <Database className="size-3.5" />
            Platform
          </span>
        ) : (
          <span className="flex items-center gap-1 rounded-lg border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-[10px] uppercase text-amber-400">
            <MonitorSmartphone className="size-3.5" />
            Offline
          </span>
        )}
        <BtnGhost onClick={() => void refreshRules()} title="Reload rules" className="px-2 py-1.5">
          <RefreshCw className="size-3.5" />
        </BtnGhost>
        <BtnPrimary onClick={onOpenCreateRule} disabled={!canPersistRules} className="px-2.5 py-1.5 text-xs">
          <Plus className="size-3.5" />
          Add Rule
        </BtnPrimary>
      </div>

      {rulesError && canPersistRules && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          {rulesError}
        </div>
      )}

      <ConsoleCard padding="none" className="overflow-hidden">
        {rulesLoading ? (
          <div className="p-16 text-center text-sm text-zinc-500">Loading alert rules from platform…</div>
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
            <table className="w-full min-w-[960px] border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-zinc-800 bg-zinc-900/80 text-[11px] uppercase text-zinc-500">
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Rule Name &amp; Target Topic</th>
                  <th className="px-4 py-3 font-medium">Condition &amp; Threshold</th>
                  <th className="px-4 py-3 font-medium">Severity</th>
                  <th className="px-4 py-3 font-medium">Triggered Roles</th>
                  <th className="px-4 py-3 text-center font-medium">Triggers</th>
                  <th className="px-4 py-3 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800/80 text-xs">
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
                      <div className="mt-1 max-w-md truncate font-mono text-xs text-zinc-500">{rule.topic}</div>
                    </td>
                    <td className="px-4 py-4">
                      <span className="rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 font-mono text-[11px] font-semibold text-[#FF7A00]">
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
                        <BtnSecondary onClick={() => onOpenEditRule(rule)} className="px-2.5 py-1 text-xs">
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
  );
};

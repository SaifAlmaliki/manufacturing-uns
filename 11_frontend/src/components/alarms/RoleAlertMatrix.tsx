import React from 'react';
import { Check, X } from 'lucide-react';
import { useAlarms } from '../../context/AlarmContext';
import { useAuth } from '../../context/AuthContext';
import { UserRole, ROLE_CONFIGS } from '../../types/rbac';
import { ConsoleCard } from '../ui/console-ui';
import { getSeverityBadge } from './alarmUi';

const PREDEFINED_ROLES: UserRole[] = ['operator', 'engineer', 'admin', 'auditor', 'viewer'];

export const RoleAlertMatrix: React.FC = () => {
  const { rules, updateRule } = useAlarms();
  const { currentUser } = useAuth();

  const handleToggleRoleTrigger = (ruleId: string, role: UserRole, currentRoles: UserRole[]) => {
    let nextRoles: UserRole[];
    if (currentRoles.includes(role)) {
      if (currentRoles.length === 1) return;
      nextRoles = currentRoles.filter((r) => r !== role);
    } else {
      nextRoles = [...currentRoles, role];
    }
    updateRule(ruleId, { targetRoles: nextRoles });
  };

  return (
    <div className="space-y-2">
      <p className="text-xs text-zinc-500 text-pretty">
        Click a cell to toggle which roles receive alerts for each rule.
      </p>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        {PREDEFINED_ROLES.map((role) => {
          const cfg = ROLE_CONFIGS[role] || ROLE_CONFIGS.viewer;
          const assignedCount = rules.filter((r) => r.targetRoles.includes(role)).length;
          const isMyRole = currentUser.role === role;

          return (
            <div
              key={role}
              className={`rounded-lg border bg-zinc-900/50 p-2.5 ${
                isMyRole ? 'border-[#FF7A00]/50 ring-1 ring-[#FF7A00]/20' : 'border-zinc-800'
              }`}
            >
              <div className="mb-1 flex items-center justify-between">
                <span className={`rounded border px-1.5 py-0.5 text-[9px] font-bold ${cfg.badgeBg} ${cfg.badgeText} ${cfg.badgeBorder}`}>
                  {role.toUpperCase()}
                </span>
                {isMyRole && <span className="text-[9px] font-bold text-[#FF7A00]">CURRENT</span>}
              </div>
              <div className="truncate text-sm font-semibold text-white">{cfg.label}</div>
              <div className="mt-1 text-[10px] text-zinc-500">
                <span className="font-semibold tabular-nums text-emerald-400">{assignedCount}</span>
                {' / '}
                {rules.length} rules
              </div>
            </div>
          );
        })}
      </div>

      <ConsoleCard padding="none" className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-zinc-800 bg-zinc-900/80 text-[11px] uppercase text-zinc-500">
                <th className="min-w-[240px] px-4 py-3 font-medium">Rule &amp; Monitored Target</th>
                <th className="px-3 py-3 font-medium">Category</th>
                <th className="px-3 py-3 font-medium">Severity</th>
                {PREDEFINED_ROLES.map((role) => (
                  <th key={role} className="min-w-[90px] px-3 py-3 text-center font-medium">
                    <div className="text-white">{role}</div>
                    <div className="text-[9px] normal-case text-zinc-500">{ROLE_CONFIGS[role]?.label?.split(' ')[0]}</div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800/80 text-xs">
              {rules.map((rule) => (
                <tr key={rule.id} className="transition-colors hover:bg-zinc-800/30">
                  <td className="px-4 py-3">
                    <div className="font-semibold text-white">{rule.name}</div>
                    <div className="max-w-xs truncate font-mono text-[10px] text-zinc-500">{rule.topic}</div>
                  </td>
                  <td className="px-3 py-3">
                    <span className="rounded border border-zinc-700 bg-zinc-900 px-2 py-0.5 text-[10px] text-zinc-400">
                      {rule.category}
                    </span>
                  </td>
                  <td className="px-3 py-3">
                    <span className={`rounded border px-2 py-0.5 text-[10px] font-bold ${getSeverityBadge(rule.severity)}`}>
                      {rule.severity}
                    </span>
                  </td>
                  {PREDEFINED_ROLES.map((role) => {
                    const isTriggered = rule.targetRoles.includes(role);
                    const isCurrentUserRole = currentUser.role === role;

                    return (
                      <td key={role} className="px-3 py-3 text-center">
                        <button
                          type="button"
                          onClick={() => handleToggleRoleTrigger(rule.id, role, rule.targetRoles)}
                          className={`mx-auto flex size-7 cursor-pointer items-center justify-center rounded-md border transition-all ${
                            isTriggered
                              ? 'border-emerald-500/50 bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30'
                              : 'border-zinc-700 bg-zinc-900 text-zinc-600 hover:border-zinc-600 hover:text-zinc-400'
                          } ${isCurrentUserRole ? 'ring-1 ring-[#FF7A00]/50' : ''}`}
                          title={`Toggle alert trigger for role '${role}'`}
                        >
                          {isTriggered ? <Check className="size-4 stroke-[3]" /> : <X className="size-3.5 opacity-40" />}
                        </button>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </ConsoleCard>
    </div>
  );
};

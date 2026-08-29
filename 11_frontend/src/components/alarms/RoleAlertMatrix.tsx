import React from 'react';
import { Shield, Check, X, Bell, Info, Sliders, AlertTriangle } from 'lucide-react';
import { useAlarms } from '../../context/AlarmContext';
import { useAuth } from '../../context/AuthContext';
import { UserRole, ROLE_CONFIGS } from '../../types/rbac';

const PREDEFINED_ROLES: UserRole[] = ['operator', 'engineer', 'admin', 'auditor', 'viewer'];

export const RoleAlertMatrix: React.FC = () => {
  const { rules, updateRule } = useAlarms();
  const { currentUser } = useAuth();

  const handleToggleRoleTrigger = (ruleId: string, role: UserRole, currentRoles: UserRole[]) => {
    let nextRoles: UserRole[];
    if (currentRoles.includes(role)) {
      if (currentRoles.length === 1) return; // Prevent removing all roles
      nextRoles = currentRoles.filter((r) => r !== role);
    } else {
      nextRoles = [...currentRoles, role];
    }
    updateRule(ruleId, { targetRoles: nextRoles });
  };

  return (
    <div className="space-y-4 font-sans text-xs">
      {/* Informational Header */}
      <div className="p-3 bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] rounded-lg flex items-start gap-3">
        <div className="w-8 h-8 rounded-lg bg-amber-50 dark:bg-[#FFC107]/10 border border-amber-200 dark:border-[#FFC107]/30 flex items-center justify-center text-amber-600 dark:text-[#FFC107] shrink-0 mt-0.5">
          <Shield className="w-4 h-4" />
        </div>
        <div>
          <h2 className="font-display font-bold text-sm text-[#0F172A] dark:text-[#F8FAFC] text-balance">
            Role-Based Alert Trigger Matrix
          </h2>
          <p className="text-[11px] text-[#64748B] dark:text-[#94A3B8] mt-0.5 text-pretty">
            Configure which predefined system roles (Operator, Engineer, Admin, Auditor, Viewer) receive live alerts and incident notifications for each monitored process envelope. Click any matrix cell to toggle routing.
          </p>
        </div>
      </div>

      {/* Role Summary Badges */}
      <div className="grid grid-cols-1 sm:grid-cols-5 gap-2 font-mono text-[11px]">
        {PREDEFINED_ROLES.map((role) => {
          const cfg = ROLE_CONFIGS[role] || ROLE_CONFIGS.viewer;
          const assignedCount = rules.filter((r) => r.targetRoles.includes(role)).length;
          const isMyRole = currentUser.role === role;

          return (
            <div
              key={role}
              className={`p-2.5 rounded-lg border bg-white dark:bg-[#111114] ${
                isMyRole ? 'border-amber-500 dark:border-[#FFC107] ring-1 ring-amber-500/30 dark:ring-[#FFC107]/30' : 'border-[#E2E8F0] dark:border-[#1E293B]'
              }`}
            >
              <div className="flex items-center justify-between mb-1">
                <span className={`px-1.5 py-0.2 rounded text-[9px] font-bold border ${cfg.badgeBg} ${cfg.badgeText} ${cfg.badgeBorder}`}>
                  {role.toUpperCase()}
                </span>
                {isMyRole && <span className="text-[9px] text-amber-700 dark:text-[#FFC107] font-bold">CURRENT</span>}
              </div>
              <div className="font-bold text-[#0F172A] dark:text-[#F8FAFC] truncate">{cfg.label}</div>
              <div className="text-[10px] text-[#64748B] mt-1">
                Triggered on <span className="text-emerald-600 dark:text-emerald-400 font-bold tabular-nums">{assignedCount}</span> / {rules.length} rules
              </div>
            </div>
          );
        })}
      </div>

      {/* Interactive Matrix Table */}
      <div className="bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] rounded-xl overflow-hidden shadow-sm dark:shadow-lg">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="border-b border-[#E2E8F0] dark:border-[#1E293B] bg-[#F8FAFC] dark:bg-[#0B0B0C] text-[#64748B] font-mono text-[10px] uppercase">
                <th className="py-3 px-4 min-w-[240px]">Rule &amp; Monitored Target</th>
                <th className="py-3 px-3">Category</th>
                <th className="py-3 px-3">Severity</th>
                {PREDEFINED_ROLES.map((role) => (
                  <th key={role} className="py-3 px-3 text-center min-w-[90px]">
                    <div className="text-[#0F172A] dark:text-[#F8FAFC] font-bold">{role}</div>
                    <div className="text-[9px] text-[#64748B] lowercase">{ROLE_CONFIGS[role]?.label?.split(' ')[0]}</div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-[#E2E8F0] dark:divide-[#1E293B]/60 font-mono text-[11px]">
              {rules.map((rule) => (
                <tr key={rule.id} className="hover:bg-slate-50 dark:hover:bg-[#1E293B]/20 transition-colors">
                  {/* Rule Name & Topic */}
                  <td className="py-3 px-4">
                    <div className="font-bold text-[#0F172A] dark:text-[#F8FAFC]">{rule.name}</div>
                    <div className="text-[10px] text-[#64748B] truncate max-w-xs">{rule.topic}</div>
                  </td>

                  {/* Category */}
                  <td className="py-3 px-3">
                    <span className="px-2 py-0.5 rounded bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#E2E8F0] dark:border-[#1E293B] text-[10px] text-[#64748B] dark:text-[#94A3B8]">
                      {rule.category}
                    </span>
                  </td>

                  {/* Severity */}
                  <td className="py-3 px-3">
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-bold border ${
                        rule.severity === 'CRITICAL'
                          ? 'bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-500/20 dark:text-rose-300 dark:border-rose-500/50'
                          : rule.severity === 'HIGH'
                          ? 'bg-amber-50 text-amber-800 border-amber-200 dark:bg-amber-500/20 dark:text-amber-300 dark:border-amber-500/50'
                          : rule.severity === 'WARNING'
                          ? 'bg-yellow-50 text-yellow-800 border-yellow-200 dark:bg-yellow-500/20 dark:text-yellow-300 dark:border-yellow-500/50'
                          : 'bg-sky-50 text-sky-700 border-sky-200 dark:bg-sky-500/20 dark:text-sky-300 dark:border-sky-500/50'
                      }`}
                    >
                      {rule.severity}
                    </span>
                  </td>

                  {/* Role Matrix Cells */}
                  {PREDEFINED_ROLES.map((role) => {
                    const isTriggered = rule.targetRoles.includes(role);
                    const isCurrentUserRole = currentUser.role === role;

                    return (
                      <td key={role} className="py-3 px-3 text-center">
                        <button
                          type="button"
                          onClick={() => handleToggleRoleTrigger(rule.id, role, rule.targetRoles)}
                          className={`w-7 h-7 mx-auto rounded-md border flex items-center justify-center transition-all cursor-pointer ${
                            isTriggered
                              ? 'bg-emerald-50 dark:bg-emerald-500/20 border-emerald-300 dark:border-emerald-500/50 text-emerald-600 dark:text-emerald-400 hover:bg-emerald-100 dark:hover:bg-emerald-500/30 shadow-sm'
                              : 'bg-[#F8FAFC] dark:bg-[#0B0B0C] border-[#E2E8F0] dark:border-[#1E293B] text-[#94A3B8] dark:text-[#334155] hover:border-[#94A3B8] dark:hover:border-[#475569] hover:text-[#64748B]'
                          } ${isCurrentUserRole ? 'ring-1 ring-amber-500 dark:ring-[#FFC107]' : ''}`}
                          title={`Toggle alert trigger for role '${role}'`}
                        >
                          {isTriggered ? (
                            <Check className="w-4 h-4 stroke-[3]" />
                          ) : (
                            <X className="w-3.5 h-3.5 opacity-40" />
                          )}
                        </button>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

import React, { useEffect, useMemo, useState } from 'react';
import { Shield, Users } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { fetchRealmMembers, type DirectoryResult } from '../../lib/auth/directory';
import { platformConfig } from '../../lib/platform/config';
import {
  UserRole,
  SYSTEM_FEATURES,
  ROLE_CONFIGS,
} from '../../types/rbac';
import { AccessRestricted } from '../common/AccessRestricted';
import {
  PageShell,
  PageContent,
  ConsoleCard,
  SegmentTabs,
  FilterToolbar,
} from '../ui/console-ui';

type SubTab = 'directory' | 'roles';

function DirectoryState({ title, body }: { title: string; body: string }) {
  return (
    <ConsoleCard padding="md" className="text-sm text-zinc-400">
      <h3 className="mb-2 font-semibold text-white">{title}</h3>
      <p className="whitespace-pre-line leading-relaxed">{body}</p>
    </ConsoleCard>
  );
}

export const UserManagementView: React.FC = () => {
  const { isAdmin } = useAuth();
  const [activeSubTab, setActiveSubTab] = useState<SubTab>('directory');
  const [result, setResult] = useState<DirectoryResult | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [roleFilter, setRoleFilter] = useState<string>('ALL');

  useEffect(() => {
    if (!isAdmin) {
      return;
    }
    let cancelled = false;
    void fetchRealmMembers().then((next) => {
      if (!cancelled) {
        setResult(next);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [isAdmin]);

  const members = result?.kind === 'members' ? result.members : [];

  const filteredMembers = useMemo(() => {
    return members.filter((member) => {
      const matchSearch =
        member.displayName.toLowerCase().includes(searchQuery.toLowerCase()) ||
        member.username.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (member.email ?? '').toLowerCase().includes(searchQuery.toLowerCase());
      const matchRole =
        roleFilter === 'ALL' ||
        (roleFilter === 'NONE' ? member.roles.length === 0 : member.roles.includes(roleFilter as UserRole));
      return matchSearch && matchRole;
    });
  }, [members, searchQuery, roleFilter]);

  const userTabs = [
    { id: 'directory', label: 'User Directory', icon: Users, badge: members.length || undefined },
    { id: 'roles', label: 'Role Profiles', icon: Shield },
  ];

  if (!isAdmin) {
    return (
      <PageShell id="user-management-view" scroll={false} className="flex flex-col font-mono">
        <AccessRestricted featureKey="user_management" />
      </PageShell>
    );
  }

  return (
    <PageShell id="user-management-view" scroll={false} className="flex flex-col font-mono">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <PageContent fullWidth className="flex min-h-full flex-col gap-3 pb-4">
          <SegmentTabs tabs={userTabs} active={activeSubTab} onChange={(id) => setActiveSubTab(id as SubTab)} />

          {activeSubTab === 'directory' && (
            <>
              {result === null && (
                <DirectoryState
                  title="Reading the realm"
                  body="Asking Keycloak who has access to this plant."
                />
              )}

              {result?.kind === 'forbidden' && (
                <DirectoryState
                  title="This console cannot read the realm's user directory"
                  body={`Your account is a console administrator, but the realm did not allow it to list users.
That needs the realm-management view-users role. Users are managed in Keycloak at
${platformConfig.authBaseUrl}/admin/${platformConfig.authRealm}/console/.`}
                />
              )}

              {result?.kind === 'unreachable' && (
                <DirectoryState
                  title="The realm did not answer"
                  body={`${result.detail} Keycloak is at ${platformConfig.authBaseUrl}. Users are managed there.`}
                />
              )}

              {result?.kind === 'members' && (
                <>
                  <FilterToolbar
                    search={{
                      value: searchQuery,
                      onChange: setSearchQuery,
                      placeholder: 'Search name, username, email…',
                    }}
                    selects={[
                      {
                        value: roleFilter,
                        onChange: setRoleFilter,
                        'aria-label': 'Role',
                        options: [
                          { value: 'ALL', label: 'All roles' },
                          { value: 'NONE', label: 'No console role' },
                          { value: 'admin', label: 'Admin' },
                          { value: 'engineer', label: 'Engineer' },
                          { value: 'operator', label: 'Operator' },
                          { value: 'auditor', label: 'Auditor' },
                          { value: 'viewer', label: 'Viewer' },
                        ],
                      },
                    ]}
                  />

                  <ConsoleCard padding="none" className="overflow-hidden">
                    <div className="overflow-x-auto">
                      <table className="w-full border-collapse text-left text-xs">
                        <thead>
                          <tr className="border-b border-zinc-800 bg-[#0a0a0b] text-[10px] uppercase tracking-wider text-zinc-500">
                            <th className="px-3 py-2.5">Name</th>
                            <th className="px-3 py-2.5">Username</th>
                            <th className="px-3 py-2.5">Email</th>
                            <th className="px-3 py-2.5">Console roles</th>
                            <th className="px-3 py-2.5">Status</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-zinc-800">
                          {filteredMembers.length === 0 ? (
                            <tr>
                              <td colSpan={5} className="py-10 text-center text-zinc-500">
                                No realm members match this filter.
                              </td>
                            </tr>
                          ) : (
                            filteredMembers.map((member) => (
                              <tr key={member.id} className="transition-colors hover:bg-zinc-800/40">
                                <td className="px-3 py-2.5 font-semibold text-white">{member.displayName}</td>
                                <td className="px-3 py-2.5 font-mono text-zinc-400">{member.username}</td>
                                <td className="px-3 py-2.5 text-zinc-500">{member.email ?? '—'}</td>
                                <td className="px-3 py-2.5">
                                  {member.roles.length === 0 ? (
                                    <span className="text-zinc-500">No console role</span>
                                  ) : (
                                    <div className="flex flex-wrap gap-1">
                                      {member.roles.map((role) => {
                                        const cfg = ROLE_CONFIGS[role];
                                        return (
                                          <span
                                            key={role}
                                            className={`rounded-md border px-2 py-0.5 text-[9px] font-bold ${cfg.badgeBg} ${cfg.badgeText} ${cfg.badgeBorder}`}
                                          >
                                            {cfg.label}
                                          </span>
                                        );
                                      })}
                                    </div>
                                  )}
                                </td>
                                <td className="px-3 py-2.5 text-[10px] text-zinc-500">
                                  {member.enabled ? 'Active' : 'Disabled in Keycloak'}
                                </td>
                              </tr>
                            ))
                          )}
                        </tbody>
                      </table>
                    </div>
                  </ConsoleCard>
                </>
              )}
            </>
          )}

          {activeSubTab === 'roles' && (
            <>
              <p className="text-xs text-zinc-500">
                These are the console&apos;s five roles and what each may open. Which role a person
                holds is decided in Keycloak; what the GraphQL service accepts from that role is
                decided by the service, not by this screen.
              </p>
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
                {(Object.keys(ROLE_CONFIGS) as UserRole[]).map((role) => {
                  const config = ROLE_CONFIGS[role];
                  return (
                    <ConsoleCard key={role} padding="sm" className="space-y-3">
                      <div className="flex items-center justify-between">
                        <span
                          className={`rounded-md border px-2.5 py-0.5 text-[10px] font-bold ${config.badgeBg} ${config.badgeText} ${config.badgeBorder}`}
                        >
                          {config.label.toUpperCase()}
                        </span>
                      </div>
                      <p className="text-[11px] leading-relaxed text-zinc-400">{config.description}</p>
                      <div className="space-y-1.5 border-t border-zinc-800 pt-2">
                        <div className="text-[9px] uppercase tracking-wider text-zinc-500">Baseline capabilities</div>
                        <div className="flex flex-wrap gap-1">
                          {SYSTEM_FEATURES.map((feat) => {
                            const isDefault = !!config.defaultPermissions[feat.key];
                            return (
                              <span
                                key={feat.key}
                                className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[9px] ${
                                  isDefault
                                    ? 'border-emerald-800/40 bg-emerald-950/40 text-emerald-400'
                                    : 'border-zinc-800 bg-zinc-950 text-zinc-600 line-through'
                                }`}
                              >
                                {feat.label}
                              </span>
                            );
                          })}
                        </div>
                      </div>
                    </ConsoleCard>
                  );
                })}
              </div>
            </>
          )}
        </PageContent>
      </div>
    </PageShell>
  );
};

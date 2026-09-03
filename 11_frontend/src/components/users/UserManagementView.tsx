import React, { useState, useMemo } from 'react';
import {
  Users,
  Shield,
  UserPlus,
  Search,
  XCircle,
  Clock,
  Check,
  X,
  FileSpreadsheet,
  Layers,
  Activity,
  History,
  Edit3,
  RotateCcw,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import {
  UserAccount,
  UserRole,
  SYSTEM_FEATURES,
  ROLE_CONFIGS,
} from '../../types/rbac';
import { CreateUserModal } from './CreateUserModal';
import { EditUserModal } from './EditUserModal';
import {
  PageShell,
  PageContent,
  ConsoleCard,
  PageStat,
  CompactKpiRow,
  SegmentTabs,
  FilterToolbar,
  BtnPrimary,
  BtnSecondary,
} from '../ui/console-ui';

type SubTab = 'directory' | 'matrix' | 'roles' | 'audit';

function grantedFeatureCount(user: UserAccount): number {
  if (user.role === 'admin') return SYSTEM_FEATURES.length;
  return SYSTEM_FEATURES.filter((f) => !!user.customPermissions?.[f.key]).length;
}

function featureAllowed(user: UserAccount, key: (typeof SYSTEM_FEATURES)[number]['key']): boolean {
  return user.role === 'admin' ? true : !!user.customPermissions?.[key];
}

export const UserManagementView: React.FC = () => {
  const { users, currentUser, auditLogs, switchUser, toggleUserFeaturePermission, restoreDefaults } = useAuth();

  const [activeSubTab, setActiveSubTab] = useState<SubTab>('directory');
  const [searchQuery, setSearchQuery] = useState('');
  const [roleFilter, setRoleFilter] = useState<string>('ALL');
  const [statusFilter, setStatusFilter] = useState<string>('ALL');

  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [selectedUserForEdit, setSelectedUserForEdit] = useState<UserAccount | null>(null);

  const filteredUsers = useMemo(() => {
    return users.filter((u) => {
      const matchSearch =
        u.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        u.email.toLowerCase().includes(searchQuery.toLowerCase()) ||
        u.department.toLowerCase().includes(searchQuery.toLowerCase()) ||
        u.plantLocation.toLowerCase().includes(searchQuery.toLowerCase());
      const matchRole = roleFilter === 'ALL' || u.role === roleFilter;
      const matchStatus = statusFilter === 'ALL' || u.status === statusFilter;
      return matchSearch && matchRole && matchStatus;
    });
  }, [users, searchQuery, roleFilter, statusFilter]);

  const stats = useMemo(() => {
    return {
      total: users.length,
      admins: users.filter((u) => u.role === 'admin').length,
      engineers: users.filter((u) => u.role === 'engineer').length,
      operators: users.filter((u) => u.role === 'operator').length,
      auditors: users.filter((u) => u.role === 'auditor').length,
      suspended: users.filter((u) => u.status === 'suspended').length,
    };
  }, [users]);

  const userTabs = [
    { id: 'directory', label: 'User Directory', icon: Users, badge: filteredUsers.length },
    { id: 'matrix', label: 'Access Matrix', icon: FileSpreadsheet },
    { id: 'roles', label: 'Role Profiles', icon: Shield },
    { id: 'audit', label: 'Audit Log', icon: History, badge: auditLogs.length },
  ];

  return (
    <PageShell id="user-management-view" scroll={false} className="flex flex-col font-mono">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <PageContent fullWidth className="flex min-h-full flex-col gap-3 pb-4">
          <CompactKpiRow
            actions={
              <>
                <BtnSecondary
                  onClick={() => {
                    if (confirm('Restore default user accounts and role definitions?')) {
                      restoreDefaults();
                    }
                  }}
                  className="px-2.5 py-1.5 text-xs"
                >
                  <RotateCcw className="size-3.5" />
                  Reset
                </BtnSecondary>
                <BtnPrimary id="create-user-btn" onClick={() => setIsCreateModalOpen(true)} className="px-2.5 py-1.5 text-xs">
                  <UserPlus className="size-3.5" />
                  New User
                </BtnPrimary>
              </>
            }
          >
            <PageStat compact label="Total" value={stats.total} icon={<Users className="size-3.5 text-zinc-400" />} iconBg="bg-zinc-800" />
            <PageStat compact label="Admins" value={stats.admins} valueClassName="text-red-400" icon={<Shield className="size-3.5 text-red-400" />} iconBg="bg-red-500/15" />
            <PageStat compact label="Engineers" value={stats.engineers} valueClassName="text-[#FF7A00]" icon={<Layers className="size-3.5 text-[#FF7A00]" />} />
            <PageStat compact label="Operators" value={stats.operators} valueClassName="text-emerald-400" icon={<Activity className="size-3.5 text-emerald-400" />} iconBg="bg-emerald-500/15" />
            <PageStat compact label="Auditors" value={stats.auditors} valueClassName="text-purple-400" icon={<Search className="size-3.5 text-purple-400" />} iconBg="bg-purple-500/15" />
            <PageStat compact label="Suspended" value={stats.suspended} icon={<XCircle className="size-3.5 text-zinc-500" />} iconBg="bg-zinc-800" />
          </CompactKpiRow>

          <SegmentTabs tabs={userTabs} active={activeSubTab} onChange={(id) => setActiveSubTab(id as SubTab)} />

          {activeSubTab === 'directory' && (
            <>
              <FilterToolbar
                search={{
                  value: searchQuery,
                  onChange: setSearchQuery,
                  placeholder: 'Search name, email, department, site…',
                }}
                selects={[
                  {
                    value: roleFilter,
                    onChange: setRoleFilter,
                    'aria-label': 'Role',
                    options: [
                      { value: 'ALL', label: 'All roles' },
                      { value: 'admin', label: 'Admin' },
                      { value: 'engineer', label: 'Engineer' },
                      { value: 'operator', label: 'Operator' },
                      { value: 'auditor', label: 'Auditor' },
                      { value: 'viewer', label: 'Viewer' },
                    ],
                  },
                  {
                    value: statusFilter,
                    onChange: setStatusFilter,
                    'aria-label': 'Status',
                    options: [
                      { value: 'ALL', label: 'All statuses' },
                      { value: 'active', label: 'Active' },
                      { value: 'suspended', label: 'Suspended' },
                      { value: 'pending', label: 'Pending' },
                    ],
                  },
                ]}
              />

              <ConsoleCard padding="none" className="overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full border-collapse text-left text-xs">
                    <thead>
                      <tr className="border-b border-zinc-800 bg-[#0a0a0b] text-[10px] uppercase tracking-wider text-zinc-500">
                        <th className="px-3 py-2.5">Identity &amp; Account</th>
                        <th className="px-3 py-2.5">Role Profile</th>
                        <th className="px-3 py-2.5">Plant &amp; Department</th>
                        <th className="px-3 py-2.5">Status</th>
                        <th className="px-3 py-2.5">Granted Features</th>
                        <th className="px-3 py-2.5">Last Active</th>
                        <th className="px-3 py-2.5 text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-zinc-800">
                      {filteredUsers.length === 0 ? (
                        <tr>
                          <td colSpan={7} className="py-10 text-center text-zinc-500">
                            No users found matching query criteria.
                          </td>
                        </tr>
                      ) : (
                        filteredUsers.map((user) => {
                          const isSelf = user.id === currentUser.id;
                          const roleConfig = ROLE_CONFIGS[user.role] || ROLE_CONFIGS.viewer;
                          const allowedCount = grantedFeatureCount(user);

                          return (
                            <tr
                              key={user.id}
                              className={`transition-colors hover:bg-zinc-800/40 ${isSelf ? 'bg-zinc-800/20' : ''}`}
                            >
                              <td className="px-3 py-2.5">
                                <div className="flex items-center gap-2.5">
                                  <div
                                    className={`flex size-7 shrink-0 items-center justify-center rounded-full text-xs font-bold text-black ${user.avatarColor || 'bg-[#FF7A00]'}`}
                                  >
                                    {user.name.charAt(0).toUpperCase()}
                                  </div>
                                  <div className="min-w-0">
                                    <div className="flex items-center gap-1.5 truncate font-semibold text-white">
                                      <span>{user.name}</span>
                                      {isSelf && (
                                        <span className="rounded border border-[#FF7A00]/30 bg-[#FF7A00]/15 px-1 py-px text-[8px] font-bold text-[#FF7A00]">
                                          YOU
                                        </span>
                                      )}
                                    </div>
                                    <div className="truncate text-[10px] text-zinc-500">{user.email}</div>
                                  </div>
                                </div>
                              </td>

                              <td className="px-3 py-2.5">
                                <span
                                  className={`rounded-md border px-2 py-0.5 text-[9px] font-bold ${roleConfig.badgeBg} ${roleConfig.badgeText} ${roleConfig.badgeBorder}`}
                                >
                                  {roleConfig.label.toUpperCase()}
                                </span>
                              </td>

                              <td className="px-3 py-2.5">
                                <div className="max-w-[160px] truncate text-[11px] text-sky-300">{user.department}</div>
                                <div className="max-w-[160px] truncate text-[9px] text-zinc-500">{user.plantLocation}</div>
                              </td>

                              <td className="px-3 py-2.5">
                                {user.status === 'active' && (
                                  <span className="inline-flex items-center gap-1.5 text-[10px] text-emerald-400">
                                    <span className="relative flex size-2">
                                      <span className="absolute inline-flex size-full animate-ping rounded-full bg-emerald-400 opacity-40" />
                                      <span className="relative inline-flex size-2 rounded-full bg-emerald-400" />
                                    </span>
                                    Active
                                  </span>
                                )}
                                {user.status === 'suspended' && (
                                  <span className="inline-flex items-center gap-1 text-[10px] text-rose-400">
                                    <XCircle className="size-3" />
                                    Suspended
                                  </span>
                                )}
                                {user.status === 'pending' && (
                                  <span className="inline-flex items-center gap-1 text-[10px] text-amber-400">
                                    <Clock className="size-3" />
                                    Pending
                                  </span>
                                )}
                              </td>

                              <td className="px-3 py-2.5">
                                <div className="text-[10px]">
                                  <span className="font-bold text-[#FF7A00]">{allowedCount}</span>
                                  <span className="text-zinc-500"> / {SYSTEM_FEATURES.length} features</span>
                                </div>
                                <div className="mt-1 flex flex-wrap gap-0.5">
                                  {SYSTEM_FEATURES.map((f) => (
                                    <span
                                      key={f.key}
                                      className={`size-1.5 rounded-full ${
                                        featureAllowed(user, f.key) ? 'bg-emerald-500' : 'bg-zinc-700'
                                      }`}
                                      title={`${f.label}: ${featureAllowed(user, f.key) ? 'Allowed' : 'Locked'}`}
                                    />
                                  ))}
                                </div>
                              </td>

                              <td className="px-3 py-2.5 text-[10px] text-zinc-500">
                                {user.lastLogin === 'Never'
                                  ? 'Never'
                                  : new Date(user.lastLogin).toLocaleString(undefined, {
                                      month: 'short',
                                      day: 'numeric',
                                      hour: '2-digit',
                                      minute: '2-digit',
                                    })}
                              </td>

                              <td className="px-3 py-2.5 text-right">
                                <div className="flex items-center justify-end gap-1.5">
                                  {!isSelf && (
                                    <button
                                      type="button"
                                      onClick={() => switchUser(user.id)}
                                      className="rounded-lg border border-zinc-800 px-2 py-1 text-[10px] text-zinc-400 transition-colors hover:border-[#FF7A00]/50 hover:text-[#FF7A00]"
                                      title={`Simulate session as ${user.name}`}
                                    >
                                      Simulate
                                    </button>
                                  )}
                                  <button
                                    type="button"
                                    onClick={() => setSelectedUserForEdit(user)}
                                    className="inline-flex items-center gap-1 rounded-lg border border-zinc-700 bg-zinc-900 px-2.5 py-1 text-[10px] font-bold text-white transition-colors hover:border-zinc-500"
                                    title="Edit permissions & role"
                                  >
                                    <Edit3 className="size-3 text-[#FF7A00]" />
                                    Manage
                                  </button>
                                </div>
                              </td>
                            </tr>
                          );
                        })
                      )}
                    </tbody>
                  </table>
                </div>
              </ConsoleCard>
            </>
          )}

          {activeSubTab === 'matrix' && (
            <>
              <div className="flex flex-wrap items-center justify-between gap-2 text-[10px] text-zinc-500">
                <span>
                  Click cells to grant or revoke.{' '}
                  <span className="font-semibold text-emerald-400">Live · auto-saved</span>
                </span>
                <div className="flex items-center gap-3">
                  <span className="inline-flex items-center gap-1">
                    <span className="size-2.5 rounded bg-emerald-500" />
                    Granted
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <span className="size-2.5 rounded border border-zinc-600 bg-zinc-900" />
                    Revoked
                  </span>
                </div>
              </div>

              <ConsoleCard padding="none" className="overflow-x-auto">
                <table className="w-full border-collapse text-left text-xs">
                  <thead>
                    <tr className="border-b border-zinc-800 bg-[#0a0a0b] text-[10px] uppercase tracking-wider text-zinc-500">
                      <th className="sticky left-0 z-10 min-w-[180px] bg-[#0a0a0b] px-3 py-2.5">User Account</th>
                      <th className="min-w-[70px] px-2 py-2.5 text-center">Role</th>
                      {SYSTEM_FEATURES.map((f) => (
                        <th key={f.key} className="min-w-[100px] px-2 py-2.5 text-center" title={f.description}>
                          <div className="truncate">{f.label}</div>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-800">
                    {users.map((user) => {
                      const roleConfig = ROLE_CONFIGS[user.role] || ROLE_CONFIGS.viewer;
                      const isSuperAdmin = user.role === 'admin';

                      return (
                        <tr key={user.id} className="transition-colors hover:bg-zinc-800/30">
                          <td className="sticky left-0 z-10 border-r border-zinc-800 bg-[#111114] px-3 py-2.5">
                            <div className="flex items-center gap-2">
                              <div
                                className={`flex size-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold text-black ${user.avatarColor || 'bg-[#FF7A00]'}`}
                              >
                                {user.name.charAt(0).toUpperCase()}
                              </div>
                              <div className="truncate">
                                <div className="truncate text-[11px] font-semibold text-white">{user.name}</div>
                                <div className="truncate text-[9px] text-zinc-500">{user.email}</div>
                              </div>
                            </div>
                          </td>
                          <td className="border-r border-zinc-800 px-2 py-2 text-center">
                            <span
                              className={`rounded border px-1.5 py-px text-[8px] font-bold ${roleConfig.badgeBg} ${roleConfig.badgeText} ${roleConfig.badgeBorder}`}
                            >
                              {user.role.toUpperCase()}
                            </span>
                          </td>
                          {SYSTEM_FEATURES.map((feat) => {
                            const isAllowed = featureAllowed(user, feat.key);
                            return (
                              <td key={feat.key} className="px-2 py-2 text-center">
                                {isSuperAdmin ? (
                                  <span
                                    className="inline-flex size-5 items-center justify-center rounded border border-rose-800/60 bg-rose-950/60 text-[10px] font-bold text-rose-400"
                                    title="SuperAdmin has universal access"
                                  >
                                    ✓
                                  </span>
                                ) : (
                                  <button
                                    type="button"
                                    onClick={() => toggleUserFeaturePermission(user.id, feat.key, !isAllowed)}
                                    className={`inline-flex size-5 items-center justify-center rounded border transition-all ${
                                      isAllowed
                                        ? 'border-emerald-400 bg-emerald-500 text-black hover:bg-emerald-400'
                                        : 'border-zinc-800 bg-[#0a0a0b] text-zinc-600 hover:border-zinc-600'
                                    }`}
                                    title={`Toggle ${feat.label} for ${user.name}`}
                                  >
                                    {isAllowed && <Check className="size-3 stroke-[3]" />}
                                  </button>
                                )}
                              </td>
                            );
                          })}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </ConsoleCard>
            </>
          )}

          {activeSubTab === 'roles' && (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
              {(Object.keys(ROLE_CONFIGS) as UserRole[]).map((r) => {
                const config = ROLE_CONFIGS[r];
                const activeCount = users.filter((u) => u.role === r).length;

                return (
                  <ConsoleCard key={r} padding="sm" className="space-y-3">
                    <div className="flex items-center justify-between">
                      <span
                        className={`rounded-md border px-2.5 py-0.5 text-[10px] font-bold ${config.badgeBg} ${config.badgeText} ${config.badgeBorder}`}
                      >
                        {config.label.toUpperCase()}
                      </span>
                      <span className="text-[10px] text-zinc-500">{activeCount} users assigned</span>
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
                              className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[9px] ${
                                isDefault
                                  ? 'border-emerald-800/40 bg-emerald-950/40 text-emerald-400'
                                  : 'border-zinc-800 bg-zinc-950 text-zinc-600 line-through'
                              }`}
                            >
                              {isDefault ? <Check className="size-2.5" /> : <X className="size-2.5" />}
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
          )}

          {activeSubTab === 'audit' && (
            <ConsoleCard padding="none" className="overflow-hidden">
              <table className="w-full border-collapse text-left text-xs">
                <thead>
                  <tr className="border-b border-zinc-800 bg-[#0a0a0b] text-[10px] uppercase tracking-wider text-zinc-500">
                    <th className="px-3 py-2.5">Timestamp</th>
                    <th className="px-3 py-2.5">Action</th>
                    <th className="px-3 py-2.5">Actor (Admin)</th>
                    <th className="px-3 py-2.5">Target User</th>
                    <th className="px-3 py-2.5">Audit Details</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800">
                  {auditLogs.map((log) => (
                    <tr key={log.id} className="transition-colors hover:bg-zinc-800/30">
                      <td className="whitespace-nowrap px-3 py-2.5 text-[10px] text-zinc-500">
                        {new Date(log.timestamp).toLocaleString(undefined, {
                          year: 'numeric',
                          month: 'short',
                          day: 'numeric',
                          hour: '2-digit',
                          minute: '2-digit',
                          second: '2-digit',
                        })}
                      </td>
                      <td className="px-3 py-2.5">
                        <span className="rounded border border-[#FF7A00]/30 bg-[#FF7A00]/10 px-1.5 py-px text-[9px] font-bold text-[#FF7A00]">
                          {log.action}
                        </span>
                      </td>
                      <td className="px-3 py-2.5 text-white">{log.actorEmail}</td>
                      <td className="px-3 py-2.5 text-zinc-400">{log.targetUserEmail}</td>
                      <td className="px-3 py-2.5 text-zinc-200">{log.details}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </ConsoleCard>
          )}
        </PageContent>
      </div>

      <CreateUserModal isOpen={isCreateModalOpen} onClose={() => setIsCreateModalOpen(false)} />
      <EditUserModal
        user={selectedUserForEdit}
        isOpen={!!selectedUserForEdit}
        onClose={() => setSelectedUserForEdit(null)}
      />
    </PageShell>
  );
};

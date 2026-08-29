import React, { useState, useMemo } from 'react';
import {
  Users,
  Shield,
  UserPlus,
  KeyRound,
  Search,
  Filter,
  CheckCircle2,
  XCircle,
  Clock,
  Check,
  X,
  FileSpreadsheet,
  Layers,
  Radio,
  Workflow,
  Activity,
  Download,
  Send,
  Settings,
  Bookmark,
  Edit3,
  History,
  Lock,
  RotateCcw,
  Sparkles,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import {
  UserAccount,
  UserRole,
  FeatureKey,
  SYSTEM_FEATURES,
  ROLE_CONFIGS,
} from '../../types/rbac';
import { CreateUserModal } from './CreateUserModal';
import { EditUserModal } from './EditUserModal';

type SubTab = 'directory' | 'matrix' | 'roles' | 'audit';

export const UserManagementView: React.FC = () => {
  const {
    users,
    currentUser,
    auditLogs,
    isAdmin,
    switchUser,
    toggleUserFeaturePermission,
    restoreDefaults,
  } = useAuth();

  const [activeSubTab, setActiveSubTab] = useState<SubTab>('directory');
  const [searchQuery, setSearchQuery] = useState('');
  const [roleFilter, setRoleFilter] = useState<string>('ALL');
  const [statusFilter, setStatusFilter] = useState<string>('ALL');

  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [selectedUserForEdit, setSelectedUserForEdit] = useState<UserAccount | null>(null);

  // Filtered users
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

  // Statistics
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

  // Helper icon for feature
  const getFeatureIcon = (key: FeatureKey) => {
    switch (key) {
      case 'uns_tree':
        return Layers;
      case 'historian':
        return Search;
      case 'sparkplug':
        return Radio;
      case 'streams':
        return Workflow;
      case 'system_ops':
        return Activity;
      case 'user_management':
        return Users;
      case 'export_csv':
        return Download;
      case 'payload_publish':
        return Send;
      case 'settings_edit':
        return Settings;
      case 'topic_bookmarks':
        return Bookmark;
    }
  };

  return (
    <div id="user-management-view" className="flex-1 flex flex-col h-full overflow-hidden bg-[#050505] text-[#F8FAFC] font-mono text-xs select-none">
      {/* Header Bar */}
      <div className="p-3 md:p-4 bg-[#111114] border-b border-[#1E293B] flex flex-col sm:flex-row sm:items-center justify-between gap-3 shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded bg-rose-500/10 border border-rose-500/30 flex items-center justify-center text-rose-400">
            <Shield className="w-4 h-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="font-bold text-sm text-[#F8FAFC]">User Management &amp; RBAC Console</h1>
              <span className="px-1.5 py-0.2 rounded bg-rose-950/80 border border-rose-800 text-rose-300 text-[9px] font-bold">
                ADMIN ACCESS ONLY
              </span>
            </div>
            <p className="text-[10px] text-[#64748B]">
              Role-Based Access Control, granular feature authorization matrix &amp; compliance logs
            </p>
          </div>
        </div>

        {/* Global Actions */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => {
              if (confirm('Restore default user accounts and role definitions?')) {
                restoreDefaults();
              }
            }}
            className="px-2.5 py-1 rounded bg-[#0B0B0C] border border-[#1E293B] hover:bg-[#1E293B] text-[#94A3B8] hover:text-[#F8FAFC] text-[10px] flex items-center gap-1.5 transition-colors cursor-pointer"
            title="Reset to default seed users and matrix"
          >
            <RotateCcw className="w-3 h-3" />
            <span className="hidden md:inline">Reset Defaults</span>
          </button>

          <button
            id="create-user-btn"
            onClick={() => setIsCreateModalOpen(true)}
            className="px-3 py-1.5 rounded bg-[#FFC107] hover:bg-[#FFB300] text-black font-bold text-xs flex items-center gap-1.5 shadow-sm transition-colors cursor-pointer"
          >
            <UserPlus className="w-3.5 h-3.5" />
            <span>New User Account</span>
          </button>
        </div>
      </div>

      {/* Subsystem Metrics Strip */}
      <div className="grid grid-cols-2 sm:grid-cols-6 gap-2 p-3 bg-[#0B0B0C] border-b border-[#1E293B] text-[10px] shrink-0">
        <div className="p-2 rounded bg-[#111114] border border-[#1E293B]">
          <div className="text-[#64748B] uppercase text-[9px]">Total Accounts</div>
          <div className="text-base font-bold text-[#F8FAFC]">{stats.total}</div>
        </div>
        <div className="p-2 rounded bg-[#111114] border border-rose-500/20">
          <div className="text-rose-400 uppercase text-[9px]">Admins</div>
          <div className="text-base font-bold text-rose-400">{stats.admins}</div>
        </div>
        <div className="p-2 rounded bg-[#111114] border border-amber-500/20">
          <div className="text-[#FFC107] uppercase text-[9px]">Engineers</div>
          <div className="text-base font-bold text-[#FFC107]">{stats.engineers}</div>
        </div>
        <div className="p-2 rounded bg-[#111114] border border-emerald-500/20">
          <div className="text-emerald-400 uppercase text-[9px]">Operators</div>
          <div className="text-base font-bold text-emerald-400">{stats.operators}</div>
        </div>
        <div className="p-2 rounded bg-[#111114] border border-purple-500/20">
          <div className="text-purple-400 uppercase text-[9px]">Auditors</div>
          <div className="text-base font-bold text-purple-400">{stats.auditors}</div>
        </div>
        <div className="p-2 rounded bg-[#111114] border border-[#1E293B]">
          <div className="text-[#64748B] uppercase text-[9px]">Suspended</div>
          <div className="text-base font-bold text-[#94A3B8]">{stats.suspended}</div>
        </div>
      </div>

      {/* Sub-Navigation Tabs */}
      <div className="px-3 md:px-4 bg-[#111114] border-b border-[#1E293B] flex items-center justify-between shrink-0 overflow-x-auto scrollbar-none">
        <div className="flex items-center gap-1 min-w-max">
          <button
            id="subtab-directory"
            onClick={() => setActiveSubTab('directory')}
            className={`px-3 py-2 border-b-2 font-bold text-xs flex items-center gap-1.5 transition-colors cursor-pointer whitespace-nowrap ${
              activeSubTab === 'directory'
                ? 'border-[#FFC107] text-[#FFC107]'
                : 'border-transparent text-[#94A3B8] hover:text-[#F8FAFC]'
            }`}
          >
            <Users className="w-3.5 h-3.5" />
            <span>User Directory ({filteredUsers.length})</span>
          </button>

          <button
            id="subtab-matrix"
            onClick={() => setActiveSubTab('matrix')}
            className={`px-3 py-2 border-b-2 font-bold text-xs flex items-center gap-1.5 transition-colors cursor-pointer whitespace-nowrap ${
              activeSubTab === 'matrix'
                ? 'border-[#FFC107] text-[#FFC107]'
                : 'border-transparent text-[#94A3B8] hover:text-[#F8FAFC]'
            }`}
          >
            <FileSpreadsheet className="w-3.5 h-3.5" />
            <span>Feature Access Matrix</span>
          </button>

          <button
            id="subtab-roles"
            onClick={() => setActiveSubTab('roles')}
            className={`px-3 py-2 border-b-2 font-bold text-xs flex items-center gap-1.5 transition-colors cursor-pointer whitespace-nowrap ${
              activeSubTab === 'roles'
                ? 'border-[#FFC107] text-[#FFC107]'
                : 'border-transparent text-[#94A3B8] hover:text-[#F8FAFC]'
            }`}
          >
            <Shield className="w-3.5 h-3.5" />
            <span>Role Profiles</span>
          </button>

          <button
            id="subtab-audit"
            onClick={() => setActiveSubTab('audit')}
            className={`px-3 py-2 border-b-2 font-bold text-xs flex items-center gap-1.5 transition-colors cursor-pointer whitespace-nowrap ${
              activeSubTab === 'audit'
                ? 'border-[#FFC107] text-[#FFC107]'
                : 'border-transparent text-[#94A3B8] hover:text-[#F8FAFC]'
            }`}
          >
            <History className="w-3.5 h-3.5" />
            <span>Security Audit Log ({auditLogs.length})</span>
          </button>
        </div>
      </div>

      {/* Main Content Area */}
      <div className="flex-1 overflow-y-auto p-3 md:p-4 scrollbar-thin scrollbar-thumb-[#1E293B]">
        {/* SUBTAB 1: USER DIRECTORY */}
        {activeSubTab === 'directory' && (
          <div className="space-y-3">
            {/* Filters Bar */}
            <div className="p-2.5 rounded bg-[#111114] border border-[#1E293B] flex flex-wrap items-center justify-between gap-2.5">
              <div className="relative flex-1 min-w-[200px] max-w-md">
                <Search className="w-3.5 h-3.5 text-[#64748B] absolute left-2.5 top-2 pointer-events-none" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search user name, email, department, site..."
                  className="w-full bg-[#0B0B0C] border border-[#1E293B] rounded pl-8 pr-3 py-1 text-xs text-[#F8FAFC] focus:outline-none focus:border-[#FFC107]"
                />
              </div>

              <div className="flex items-center gap-2">
                <div className="flex items-center gap-1.5">
                  <Filter className="w-3 h-3 text-[#64748B]" />
                  <span className="text-[10px] text-[#64748B] uppercase">Role:</span>
                  <select
                    value={roleFilter}
                    onChange={(e) => setRoleFilter(e.target.value)}
                    className="bg-[#0B0B0C] border border-[#1E293B] rounded px-2 py-1 text-[11px] text-[#F8FAFC] focus:outline-none focus:border-[#FFC107]"
                  >
                    <option value="ALL">All Roles</option>
                    <option value="admin">Admin</option>
                    <option value="engineer">Engineer</option>
                    <option value="operator">Operator</option>
                    <option value="auditor">Auditor</option>
                    <option value="viewer">Viewer</option>
                  </select>
                </div>

                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] text-[#64748B] uppercase">Status:</span>
                  <select
                    value={statusFilter}
                    onChange={(e) => setStatusFilter(e.target.value)}
                    className="bg-[#0B0B0C] border border-[#1E293B] rounded px-2 py-1 text-[11px] text-[#F8FAFC] focus:outline-none focus:border-[#FFC107]"
                  >
                    <option value="ALL">All Statuses</option>
                    <option value="active">Active</option>
                    <option value="suspended">Suspended</option>
                    <option value="pending">Pending</option>
                  </select>
                </div>
              </div>
            </div>

            {/* Users Table */}
            <div className="border border-[#1E293B] rounded-lg bg-[#111114] overflow-hidden shadow-sm">
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse text-xs font-mono">
                  <thead>
                    <tr className="bg-[#0B0B0C] border-b border-[#1E293B] text-[10px] text-[#64748B] uppercase tracking-wider">
                      <th className="py-2.5 px-3">Identity &amp; Account</th>
                      <th className="py-2.5 px-3">Role Profile</th>
                      <th className="py-2.5 px-3">Plant &amp; Department</th>
                      <th className="py-2.5 px-3">Status</th>
                      <th className="py-2.5 px-3">Granted Features</th>
                      <th className="py-2.5 px-3">Last Active</th>
                      <th className="py-2.5 px-3 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#1E293B]">
                    {filteredUsers.length === 0 ? (
                      <tr>
                        <td colSpan={7} className="text-center py-10 text-[#64748B]">
                          No users found matching query criteria.
                        </td>
                      </tr>
                    ) : (
                      filteredUsers.map((user) => {
                        const isSelf = user.id === currentUser.id;
                        const roleConfig = ROLE_CONFIGS[user.role] || ROLE_CONFIGS.viewer;
                        const allowedCount = Object.values(user.customPermissions || {}).filter(Boolean).length;

                        return (
                          <tr
                            key={user.id}
                            className={`hover:bg-[#1E293B]/40 transition-colors ${
                              isSelf ? 'bg-[#1E293B]/20' : ''
                            }`}
                          >
                            {/* Identity */}
                            <td className="py-2.5 px-3">
                              <div className="flex items-center gap-2.5">
                                <div className={`w-7 h-7 rounded-full ${user.avatarColor || 'bg-[#FFC107]'} text-black flex items-center justify-center font-bold text-xs shrink-0`}>
                                  {user.name.charAt(0).toUpperCase()}
                                </div>
                                <div className="min-w-0">
                                  <div className="font-bold text-[#F8FAFC] flex items-center gap-1.5 truncate">
                                    <span>{user.name}</span>
                                    {isSelf && (
                                      <span className="px-1 py-0.2 rounded bg-amber-500/20 text-[#FFC107] text-[8px] font-bold border border-amber-500/30">
                                        YOU
                                      </span>
                                    )}
                                  </div>
                                  <div className="text-[10px] text-[#64748B] truncate">{user.email}</div>
                                </div>
                              </div>
                            </td>

                            {/* Role */}
                            <td className="py-2.5 px-3">
                              <span className={`px-2 py-0.5 rounded text-[9px] font-bold border ${roleConfig.badgeBg} ${roleConfig.badgeText} ${roleConfig.badgeBorder}`}>
                                {roleConfig.label.toUpperCase()}
                              </span>
                            </td>

                            {/* Department */}
                            <td className="py-2.5 px-3">
                              <div className="text-[11px] text-[#F8FAFC] truncate max-w-[150px]">{user.department}</div>
                              <div className="text-[9px] text-[#64748B] truncate max-w-[150px]">{user.plantLocation}</div>
                            </td>

                            {/* Status */}
                            <td className="py-2.5 px-3">
                              {user.status === 'active' && (
                                <span className="inline-flex items-center gap-1 text-emerald-400 text-[10px]">
                                  <CheckCircle2 className="w-3 h-3" />
                                  <span>Active</span>
                                </span>
                              )}
                              {user.status === 'suspended' && (
                                <span className="inline-flex items-center gap-1 text-rose-400 text-[10px]">
                                  <XCircle className="w-3 h-3" />
                                  <span>Suspended</span>
                                </span>
                              )}
                              {user.status === 'pending' && (
                                <span className="inline-flex items-center gap-1 text-amber-400 text-[10px]">
                                  <Clock className="w-3 h-3" />
                                  <span>Pending</span>
                                </span>
                              )}
                            </td>

                            {/* Granted Features */}
                            <td className="py-2.5 px-3">
                              <div className="flex items-center gap-1">
                                <span className="font-bold text-[#FFC107]">{allowedCount}</span>
                                <span className="text-[#64748B]">/ {SYSTEM_FEATURES.length} features</span>
                              </div>
                              <div className="flex gap-1 mt-1 max-w-[180px] flex-wrap">
                                {SYSTEM_FEATURES.slice(0, 5).map((f) => {
                                  const allowed = user.role === 'admin' ? true : !!user.customPermissions?.[f.key];
                                  return (
                                    <span
                                      key={f.key}
                                      className={`w-2 h-2 rounded-full ${
                                        allowed ? 'bg-emerald-500' : 'bg-[#1E293B]'
                                      }`}
                                      title={`${f.label}: ${allowed ? 'Allowed' : 'Locked'}`}
                                    />
                                  );
                                })}
                                {SYSTEM_FEATURES.length > 5 && (
                                  <span className="text-[8px] text-[#64748B]">+{SYSTEM_FEATURES.length - 5}</span>
                                )}
                              </div>
                            </td>

                            {/* Last Active */}
                            <td className="py-2.5 px-3 text-[10px] text-[#64748B]">
                              {user.lastLogin === 'Never'
                                ? 'Never'
                                : new Date(user.lastLogin).toLocaleString(undefined, {
                                    month: 'short',
                                    day: 'numeric',
                                    hour: '2-digit',
                                    minute: '2-digit',
                                  })}
                            </td>

                            {/* Actions */}
                            <td className="py-2.5 px-3 text-right">
                              <div className="flex items-center justify-end gap-1.5">
                                {!isSelf && (
                                  <button
                                    onClick={() => switchUser(user.id)}
                                    className="px-2 py-1 rounded bg-[#0B0B0C] border border-[#1E293B] hover:border-[#FFC107] text-[#94A3B8] hover:text-[#FFC107] text-[10px] transition-colors cursor-pointer"
                                    title={`Simulate session as ${user.name}`}
                                  >
                                    Simulate
                                  </button>
                                )}

                                <button
                                  onClick={() => setSelectedUserForEdit(user)}
                                  className="px-2.5 py-1 rounded bg-[#1E293B] hover:bg-[#334155] text-[#F8FAFC] text-[10px] flex items-center gap-1 transition-colors cursor-pointer font-bold"
                                  title="Edit permissions & role"
                                >
                                  <Edit3 className="w-3 h-3 text-[#FFC107]" />
                                  <span>Manage</span>
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
            </div>
          </div>
        )}

        {/* SUBTAB 2: FEATURE ACCESS MATRIX */}
        {activeSubTab === 'matrix' && (
          <div className="space-y-3">
            <div className="p-3 bg-[#111114] border border-[#1E293B] rounded-lg flex flex-col md:flex-row items-start md:items-center justify-between gap-2">
              <div>
                <h3 className="font-bold text-xs text-[#F8FAFC] flex items-center gap-2">
                  <span>Granular Feature Access Matrix</span>
                  <span className="px-1.5 py-0.2 rounded bg-emerald-950/60 border border-emerald-800 text-emerald-400 text-[9px] font-bold">
                    LIVE TOGGLE &amp; AUTO-SAVED
                  </span>
                </h3>
                <p className="text-[10px] text-[#64748B]">
                  Click checkboxes to instantly grant or revoke specific console capabilities for any user.
                </p>
              </div>

              <div className="text-[10px] text-[#94A3B8] flex items-center gap-3">
                <div className="flex items-center gap-1">
                  <span className="w-2.5 h-2.5 rounded bg-emerald-500" />
                  <span>Granted</span>
                </div>
                <div className="flex items-center gap-1">
                  <span className="w-2.5 h-2.5 rounded bg-[#1E293B] border border-[#334155]" />
                  <span>Revoked</span>
                </div>
              </div>
            </div>

            {/* Comprehensive Matrix Table */}
            <div className="border border-[#1E293B] rounded-lg bg-[#111114] overflow-x-auto shadow-sm">
              <table className="w-full text-left border-collapse text-xs font-mono">
                <thead>
                  <tr className="bg-[#0B0B0C] border-b border-[#1E293B] text-[10px] text-[#64748B] uppercase tracking-wider">
                    <th className="py-2.5 px-3 sticky left-0 bg-[#0B0B0C] z-10 min-w-[180px]">User Account</th>
                    <th className="py-2.5 px-2 text-center min-w-[70px]">Role</th>
                    {SYSTEM_FEATURES.map((f) => (
                      <th key={f.key} className="py-2.5 px-2 text-center min-w-[100px]" title={f.description}>
                        <div className="truncate">{f.label}</div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#1E293B]">
                  {users.map((user) => {
                    const roleConfig = ROLE_CONFIGS[user.role] || ROLE_CONFIGS.viewer;
                    const isSuperAdmin = user.role === 'admin';

                    return (
                      <tr key={user.id} className="hover:bg-[#1E293B]/30 transition-colors">
                        {/* Sticky User identity */}
                        <td className="py-2.5 px-3 sticky left-0 bg-[#111114] z-10 border-r border-[#1E293B]">
                          <div className="flex items-center gap-2">
                            <div className={`w-5 h-5 rounded-full ${user.avatarColor || 'bg-[#FFC107]'} text-black flex items-center justify-center font-bold text-[10px] shrink-0`}>
                              {user.name.charAt(0).toUpperCase()}
                            </div>
                            <div className="truncate">
                              <div className="font-bold text-[#F8FAFC] truncate text-[11px]">{user.name}</div>
                              <div className="text-[9px] text-[#64748B] truncate">{user.email}</div>
                            </div>
                          </div>
                        </td>

                        {/* Role */}
                        <td className="py-2 px-2 text-center border-r border-[#1E293B]">
                          <span className={`px-1.5 py-0.2 rounded text-[8px] font-bold border ${roleConfig.badgeBg} ${roleConfig.badgeText} ${roleConfig.badgeBorder}`}>
                            {user.role.toUpperCase()}
                          </span>
                        </td>

                        {/* Feature Toggles */}
                        {SYSTEM_FEATURES.map((feat) => {
                          const isAllowed = isSuperAdmin ? true : !!user.customPermissions?.[feat.key];

                          return (
                            <td key={feat.key} className="py-2 px-2 text-center">
                              {isSuperAdmin ? (
                                <span className="inline-flex items-center justify-center w-5 h-5 rounded bg-rose-950/60 border border-rose-800/60 text-rose-400 font-bold text-[10px]" title="SuperAdmin has universal access">
                                  ✓
                                </span>
                              ) : (
                                <button
                                  type="button"
                                  onClick={() => toggleUserFeaturePermission(user.id, feat.key, !isAllowed)}
                                  className={`w-5 h-5 rounded inline-flex items-center justify-center transition-all cursor-pointer border ${
                                    isAllowed
                                      ? 'bg-emerald-500 border-emerald-400 text-black font-bold shadow-xs hover:bg-emerald-400'
                                      : 'bg-[#0B0B0C] border-[#1E293B] text-[#475569] hover:border-[#334155]'
                                  }`}
                                  title={`Toggle ${feat.label} for ${user.name}`}
                                >
                                  {isAllowed && <Check className="w-3 h-3 stroke-[3]" />}
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
            </div>
          </div>
        )}

        {/* SUBTAB 3: ROLE PROFILES */}
        {activeSubTab === 'roles' && (
          <div className="space-y-3">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {(Object.keys(ROLE_CONFIGS) as UserRole[]).map((r) => {
                const config = ROLE_CONFIGS[r];
                const activeCount = users.filter((u) => u.role === r).length;

                return (
                  <div
                    key={r}
                    className="p-4 rounded-lg bg-[#111114] border border-[#1E293B] space-y-3 shadow-sm hover:border-[#334155] transition-colors"
                  >
                    <div className="flex items-center justify-between">
                      <span className={`px-2.5 py-0.5 rounded text-[10px] font-bold border ${config.badgeBg} ${config.badgeText} ${config.badgeBorder}`}>
                        {config.label.toUpperCase()}
                      </span>
                      <span className="text-[10px] text-[#64748B]">{activeCount} Users Assigned</span>
                    </div>

                    <p className="text-[11px] text-[#94A3B8] leading-relaxed">{config.description}</p>

                    {/* Default Granted Features */}
                    <div className="pt-2 border-t border-[#1E293B] space-y-1.5">
                      <div className="text-[9px] uppercase tracking-wider text-[#64748B]">
                        Baseline Capabilities:
                      </div>
                      <div className="flex flex-wrap gap-1">
                        {SYSTEM_FEATURES.map((feat) => {
                          const isDefault = !!config.defaultPermissions[feat.key];
                          return (
                            <span
                              key={feat.key}
                              className={`px-1.5 py-0.5 rounded text-[9px] flex items-center gap-1 border ${
                                isDefault
                                  ? 'bg-emerald-950/40 border-emerald-800/40 text-emerald-400'
                                  : 'bg-[#0B0B0C] border-[#1E293B] text-[#475569] line-through'
                              }`}
                            >
                              {isDefault ? <Check className="w-2.5 h-2.5" /> : <X className="w-2.5 h-2.5" />}
                              <span>{feat.label}</span>
                            </span>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* SUBTAB 4: SECURITY AUDIT LOG */}
        {activeSubTab === 'audit' && (
          <div className="space-y-3">
            <div className="p-3 bg-[#111114] border border-[#1E293B] rounded-lg flex items-center justify-between">
              <div>
                <h3 className="font-bold text-xs text-[#F8FAFC]">Security &amp; RBAC Audit Trail</h3>
                <p className="text-[10px] text-[#64748B]">
                  Immutable ledger tracking user additions, role transitions, and permission grants.
                </p>
              </div>
              <span className="px-2 py-0.5 rounded bg-[#0B0B0C] border border-[#1E293B] text-[#FFC107] text-[10px] font-bold">
                {auditLogs.length} Events Recorded
              </span>
            </div>

            <div className="border border-[#1E293B] rounded-lg bg-[#111114] overflow-hidden shadow-sm">
              <table className="w-full text-left border-collapse text-xs font-mono">
                <thead>
                  <tr className="bg-[#0B0B0C] border-b border-[#1E293B] text-[10px] text-[#64748B] uppercase tracking-wider">
                    <th className="py-2.5 px-3">Timestamp</th>
                    <th className="py-2.5 px-3">Action</th>
                    <th className="py-2.5 px-3">Actor (Admin)</th>
                    <th className="py-2.5 px-3">Target User</th>
                    <th className="py-2.5 px-3">Audit Details</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#1E293B]">
                  {auditLogs.map((log) => (
                    <tr key={log.id} className="hover:bg-[#1E293B]/30 transition-colors">
                      <td className="py-2.5 px-3 text-[10px] text-[#64748B] whitespace-nowrap">
                        {new Date(log.timestamp).toLocaleString(undefined, {
                          year: 'numeric',
                          month: 'short',
                          day: 'numeric',
                          hour: '2-digit',
                          minute: '2-digit',
                          second: '2-digit',
                        })}
                      </td>
                      <td className="py-2.5 px-3">
                        <span className="px-1.5 py-0.2 rounded bg-amber-500/10 border border-amber-500/30 text-[#FFC107] text-[9px] font-bold">
                          {log.action}
                        </span>
                      </td>
                      <td className="py-2.5 px-3 text-[#F8FAFC]">{log.actorEmail}</td>
                      <td className="py-2.5 px-3 text-[#94A3B8]">{log.targetUserEmail}</td>
                      <td className="py-2.5 px-3 text-[#F8FAFC]">{log.details}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* Modals */}
      <CreateUserModal
        isOpen={isCreateModalOpen}
        onClose={() => setIsCreateModalOpen(false)}
      />

      <EditUserModal
        user={selectedUserForEdit}
        isOpen={!!selectedUserForEdit}
        onClose={() => setSelectedUserForEdit(null)}
      />
    </div>
  );
};

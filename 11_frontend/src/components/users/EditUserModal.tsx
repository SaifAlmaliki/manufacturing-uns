import React, { useState, useEffect } from 'react';
import { X, Shield, Check, Info, AlertTriangle, RefreshCw, Trash2 } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { UserAccount, UserRole, FeatureKey, SYSTEM_FEATURES, ROLE_CONFIGS } from '../../types/rbac';

interface EditUserModalProps {
  user: UserAccount | null;
  isOpen: boolean;
  onClose: () => void;
}

export const EditUserModal: React.FC<EditUserModalProps> = ({ user, isOpen, onClose }) => {
  const { updateUser, deleteUser, resetUserToRoleDefaults, currentUser } = useAuth();

  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<UserRole>('operator');
  const [status, setStatus] = useState<'active' | 'suspended' | 'pending'>('active');
  const [department, setDepartment] = useState('');
  const [plantLocation, setPlantLocation] = useState('');
  const [notes, setNotes] = useState('');
  const [customPermissions, setCustomPermissions] = useState<Record<FeatureKey, boolean>>({} as Record<FeatureKey, boolean>);

  useEffect(() => {
    if (user) {
      setName(user.name);
      setEmail(user.email);
      setRole(user.role);
      setStatus(user.status);
      setDepartment(user.department || '');
      setPlantLocation(user.plantLocation || '');
      setNotes(user.notes || '');
      setCustomPermissions({ ...user.customPermissions });
    }
  }, [user]);

  if (!isOpen || !user) return null;

  const togglePermission = (key: FeatureKey) => {
    setCustomPermissions((prev) => ({
      ...prev,
      [key]: !prev[key],
    }));
  };

  const handleApplyRoleDefaults = (r: UserRole) => {
    setRole(r);
    setCustomPermissions({ ...ROLE_CONFIGS[r].defaultPermissions });
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !email.trim()) return;

    updateUser(user.id, {
      name: name.trim(),
      email: email.trim(),
      role,
      status,
      department: department.trim(),
      plantLocation: plantLocation.trim(),
      notes: notes.trim(),
      customPermissions,
    });

    onClose();
  };

  const handleDelete = () => {
    if (confirm(`Are you sure you want to delete user account '${user.name}'?`)) {
      deleteUser(user.id);
      onClose();
    }
  };

  const isSelf = user.id === currentUser.id;

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-black/70 backdrop-blur-xs flex items-center justify-center p-4">
      <div className="w-full max-w-2xl bg-[#111114] border border-[#1E293B] rounded-lg shadow-2xl overflow-hidden font-mono text-xs animate-in zoom-in-95 duration-150 flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="p-4 bg-[#0B0B0C] border-b border-[#1E293B] flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className={`w-7 h-7 rounded-full ${user.avatarColor || 'bg-[#FFC107]'} text-black flex items-center justify-center font-bold text-xs`}>
              {user.name.charAt(0).toUpperCase()}
            </div>
            <div>
              <h3 className="font-bold text-[#F8FAFC] text-sm flex items-center gap-2">
                <span>Manage User: {user.name}</span>
                {isSelf && (
                  <span className="px-1.5 py-0.2 rounded bg-amber-500/20 text-[#FFC107] text-[9px] border border-amber-500/40">
                    Active Session
                  </span>
                )}
              </h3>
              <p className="text-[10px] text-[#64748B]">{user.email} &bull; ID: {user.id}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded bg-[#111114] border border-[#1E293B] hover:bg-[#1E293B] text-[#64748B] hover:text-[#F8FAFC] cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Form Body */}
        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto p-4 space-y-4 scrollbar-thin scrollbar-thumb-[#1E293B]">
          {/* Identity & Status */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div>
              <label className="block text-[10px] text-[#94A3B8] uppercase font-bold mb-1">Full Name</label>
              <input
                type="text"
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full bg-[#0B0B0C] border border-[#1E293B] rounded px-3 py-1.5 text-xs text-[#F8FAFC] focus:outline-none focus:border-[#FFC107]"
              />
            </div>
            <div>
              <label className="block text-[10px] text-[#94A3B8] uppercase font-bold mb-1">Email Address</label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full bg-[#0B0B0C] border border-[#1E293B] rounded px-3 py-1.5 text-xs text-[#F8FAFC] focus:outline-none focus:border-[#FFC107]"
              />
            </div>
            <div>
              <label className="block text-[10px] text-[#94A3B8] uppercase font-bold mb-1">Account Status</label>
              <select
                value={status}
                onChange={(e) => setStatus(e.target.value as 'active' | 'suspended' | 'pending')}
                className="w-full bg-[#0B0B0C] border border-[#1E293B] rounded px-2.5 py-1.5 text-xs text-[#F8FAFC] focus:outline-none focus:border-[#FFC107]"
              >
                <option value="active">Active (Granted Access)</option>
                <option value="suspended">Suspended (Blocked)</option>
                <option value="pending">Pending Verification</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-[10px] text-[#94A3B8] uppercase font-bold mb-1">Department</label>
              <input
                type="text"
                value={department}
                onChange={(e) => setDepartment(e.target.value)}
                className="w-full bg-[#0B0B0C] border border-[#1E293B] rounded px-3 py-1.5 text-xs text-[#F8FAFC] focus:outline-none focus:border-[#FFC107]"
              />
            </div>
            <div>
              <label className="block text-[10px] text-[#94A3B8] uppercase font-bold mb-1">Plant / Site</label>
              <input
                type="text"
                value={plantLocation}
                onChange={(e) => setPlantLocation(e.target.value)}
                className="w-full bg-[#0B0B0C] border border-[#1E293B] rounded px-3 py-1.5 text-xs text-[#F8FAFC] focus:outline-none focus:border-[#FFC107]"
              />
            </div>
          </div>

          {/* Role Profile Selection */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-[10px] text-[#94A3B8] uppercase font-bold">
                Assigned Role Profile
              </label>
              <button
                type="button"
                onClick={() => handleApplyRoleDefaults(role)}
                className="text-[10px] text-[#FFC107] hover:underline flex items-center gap-1 cursor-pointer"
                title="Reset all feature checkboxes to match this role's default blueprint"
              >
                <RefreshCw className="w-2.5 h-2.5" />
                <span>Reset to {role.toUpperCase()} defaults</span>
              </button>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
              {(Object.keys(ROLE_CONFIGS) as UserRole[]).map((r) => {
                const config = ROLE_CONFIGS[r];
                const isSelected = role === r;
                return (
                  <button
                    key={r}
                    type="button"
                    onClick={() => handleApplyRoleDefaults(r)}
                    className={`p-2 rounded text-left border transition-all cursor-pointer ${
                      isSelected
                        ? 'bg-[#1E293B] border-[#FFC107] text-[#F8FAFC] shadow-sm'
                        : 'bg-[#0B0B0C] border-[#1E293B] text-[#94A3B8] hover:border-[#334155]'
                    }`}
                  >
                    <div className="font-bold text-[11px] flex items-center justify-between">
                      <span>{config.label.split(' ')[0]}</span>
                      {isSelected && <Check className="w-3 h-3 text-[#FFC107]" />}
                    </div>
                    <div className="text-[9px] text-[#64748B] mt-0.5">{r.toUpperCase()}</div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Granular Feature Permissions Checklist */}
          <div className="pt-2 border-t border-[#1E293B]">
            <div className="flex items-center justify-between mb-2">
              <div>
                <label className="text-[10px] text-[#94A3B8] uppercase font-bold">
                  Granular Feature Access Matrix for {name}
                </label>
                <p className="text-[10px] text-[#64748B]">
                  Toggle individual console features on or off specifically for this user.
                </p>
              </div>
              <span className="text-[10px] font-bold text-[#FFC107] px-2 py-0.5 rounded bg-[#0B0B0C] border border-[#1E293B]">
                {Object.values(customPermissions).filter(Boolean).length} / {SYSTEM_FEATURES.length} Allowed
              </span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 bg-[#0B0B0C] p-2.5 rounded border border-[#1E293B]">
              {SYSTEM_FEATURES.map((feat) => {
                const isEnabled = !!customPermissions[feat.key];
                return (
                  <div
                    key={feat.key}
                    onClick={() => togglePermission(feat.key)}
                    className={`p-2 rounded border cursor-pointer flex items-start justify-between gap-2 transition-colors ${
                      isEnabled
                        ? 'bg-[#111114] border-emerald-500/40 text-[#F8FAFC]'
                        : 'bg-[#0B0B0C] border-[#1E293B] text-[#64748B] opacity-60 hover:opacity-100'
                    }`}
                  >
                    <div>
                      <div className="font-bold text-[11px] flex items-center gap-1.5">
                        <span className={isEnabled ? 'text-emerald-400' : 'text-[#64748B]'}>
                          {feat.label}
                        </span>
                        {feat.adminOnly && (
                          <span className="px-1 py-0.2 rounded bg-rose-950/60 border border-rose-800/60 text-rose-400 text-[8px] font-bold">
                            ADMIN
                          </span>
                        )}
                      </div>
                      <div className="text-[9px] text-[#64748B] leading-tight mt-0.5">{feat.description}</div>
                    </div>

                    <div
                      className={`w-4 h-4 rounded flex items-center justify-center shrink-0 border ${
                        isEnabled
                          ? 'bg-emerald-500 border-emerald-400 text-black font-bold'
                          : 'bg-[#111114] border-[#1E293B]'
                      }`}
                    >
                      {isEnabled && <Check className="w-3 h-3 stroke-[3]" />}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Notes */}
          <div>
            <label className="block text-[10px] text-[#94A3B8] uppercase font-bold mb-1">Administrative Notes</label>
            <input
              type="text"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="e.g. Authorized by Operations Director"
              className="w-full bg-[#0B0B0C] border border-[#1E293B] rounded px-3 py-1.5 text-xs text-[#F8FAFC] focus:outline-none focus:border-[#FFC107]"
            />
          </div>

          {/* Footer Actions */}
          <div className="pt-3 border-t border-[#1E293B] flex items-center justify-between">
            <div>
              {!isSelf && (
                <button
                  type="button"
                  onClick={handleDelete}
                  className="px-3 py-1.5 rounded bg-rose-950/30 border border-rose-800/50 hover:bg-rose-950/60 text-rose-400 text-xs flex items-center gap-1.5 transition-colors cursor-pointer"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                  <span>Delete Account</span>
                </button>
              )}
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={onClose}
                className="px-3 py-1.5 rounded bg-[#0B0B0C] border border-[#1E293B] hover:bg-[#1E293B] text-[#94A3B8] hover:text-[#F8FAFC] cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="px-4 py-1.5 rounded bg-[#FFC107] hover:bg-[#FFB300] text-black font-bold transition-colors cursor-pointer"
              >
                Save Changes
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
};

import React, { useState } from 'react';
import { X, UserPlus, Shield, Check, Info } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { UserRole, FeatureKey, SYSTEM_FEATURES, ROLE_CONFIGS } from '../../types/rbac';

interface CreateUserModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const CreateUserModal: React.FC<CreateUserModalProps> = ({ isOpen, onClose }) => {
  const { createUser } = useAuth();

  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<UserRole>('operator');
  const [department, setDepartment] = useState('Plant Automation & Control');
  const [plantLocation, setPlantLocation] = useState('Dormagen Plant');
  const [notes, setNotes] = useState('');

  // Granular feature permissions initialized from selected role defaults
  const [customPermissions, setCustomPermissions] = useState<Record<FeatureKey, boolean>>(() => ({
    ...ROLE_CONFIGS.operator.defaultPermissions,
  }));

  if (!isOpen) return null;

  const handleRoleChange = (newRole: UserRole) => {
    setRole(newRole);
    setCustomPermissions({ ...ROLE_CONFIGS[newRole].defaultPermissions });
  };

  const togglePermission = (key: FeatureKey) => {
    setCustomPermissions((prev) => ({
      ...prev,
      [key]: !prev[key],
    }));
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !email.trim()) return;

    createUser({
      name: name.trim(),
      email: email.trim(),
      role,
      department: department.trim() || 'Operations',
      plantLocation: plantLocation.trim() || 'Dormagen Plant',
      status: 'active',
      customPermissions,
      notes: notes.trim(),
    });

    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-black/70 backdrop-blur-xs flex items-center justify-center p-4">
      <div className="w-full max-w-2xl bg-[#111114] border border-[#1E293B] rounded-lg shadow-2xl overflow-hidden font-mono text-xs animate-in zoom-in-95 duration-150 flex flex-col max-h-[90vh]">
        {/* Modal Header */}
        <div className="p-4 bg-[#0B0B0C] border-b border-[#1E293B] flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded bg-[#FFC107] text-black flex items-center justify-center font-bold">
              <UserPlus className="w-3.5 h-3.5" />
            </div>
            <div>
              <h3 className="font-bold text-[#F8FAFC] text-sm">Provision New User Account</h3>
              <p className="text-[10px] text-[#64748B]">Assign identity, baseline role, and granular feature access</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded bg-[#111114] border border-[#1E293B] hover:bg-[#1E293B] text-[#64748B] hover:text-[#F8FAFC] cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Modal Form Content */}
        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto p-4 space-y-4 scrollbar-thin scrollbar-thumb-[#1E293B]">
          {/* Identity Fields */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-[10px] text-[#94A3B8] uppercase font-bold mb-1">Full Name *</label>
              <input
                type="text"
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Klaus Schneider"
                className="w-full bg-[#0B0B0C] border border-[#1E293B] rounded px-3 py-1.5 text-xs text-[#F8FAFC] focus:outline-none focus:border-[#FFC107]"
              />
            </div>
            <div>
              <label className="block text-[10px] text-[#94A3B8] uppercase font-bold mb-1">Corporate Email *</label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="e.g. k.schneider@covestro.com"
                className="w-full bg-[#0B0B0C] border border-[#1E293B] rounded px-3 py-1.5 text-xs text-[#F8FAFC] focus:outline-none focus:border-[#FFC107]"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-[10px] text-[#94A3B8] uppercase font-bold mb-1">Department</label>
              <input
                type="text"
                value={department}
                onChange={(e) => setDepartment(e.target.value)}
                placeholder="e.g. Automation & Telemetry"
                className="w-full bg-[#0B0B0C] border border-[#1E293B] rounded px-3 py-1.5 text-xs text-[#F8FAFC] focus:outline-none focus:border-[#FFC107]"
              />
            </div>
            <div>
              <label className="block text-[10px] text-[#94A3B8] uppercase font-bold mb-1">Plant / Site Location</label>
              <input
                type="text"
                value={plantLocation}
                onChange={(e) => setPlantLocation(e.target.value)}
                placeholder="e.g. Dormagen Plant, Building K12"
                className="w-full bg-[#0B0B0C] border border-[#1E293B] rounded px-3 py-1.5 text-xs text-[#F8FAFC] focus:outline-none focus:border-[#FFC107]"
              />
            </div>
          </div>

          {/* Role Selection */}
          <div>
            <label className="block text-[10px] text-[#94A3B8] uppercase font-bold mb-1.5">
              Select Primary Role Profile (Applies Baseline Template)
            </label>
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
              {(Object.keys(ROLE_CONFIGS) as UserRole[]).map((r) => {
                const config = ROLE_CONFIGS[r];
                const isSelected = role === r;
                return (
                  <button
                    key={r}
                    type="button"
                    onClick={() => handleRoleChange(r)}
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
            <p className="text-[10px] text-[#64748B] mt-1.5 flex items-center gap-1">
              <Info className="w-3 h-3 text-[#FFC107]" />
              <span>{ROLE_CONFIGS[role].description}</span>
            </p>
          </div>

          {/* Granular Feature Permissions Matrix */}
          <div className="pt-2 border-t border-[#1E293B]">
            <div className="flex items-center justify-between mb-2">
              <label className="text-[10px] text-[#94A3B8] uppercase font-bold">
                Granular Feature Permissions Override
              </label>
              <span className="text-[10px] text-[#64748B]">
                {Object.values(customPermissions).filter(Boolean).length} / {SYSTEM_FEATURES.length} features enabled
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
              placeholder="e.g. Granted by SecOps for Phase 2 integration test"
              className="w-full bg-[#0B0B0C] border border-[#1E293B] rounded px-3 py-1.5 text-xs text-[#F8FAFC] focus:outline-none focus:border-[#FFC107]"
            />
          </div>

          {/* Footer Actions */}
          <div className="pt-3 border-t border-[#1E293B] flex items-center justify-end gap-2">
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
              Create Account
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

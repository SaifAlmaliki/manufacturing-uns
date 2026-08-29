import React from 'react';
import { ShieldAlert, Lock, ArrowRight, UserCheck, KeyRound } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { FeatureKey, SYSTEM_FEATURES, ROLE_CONFIGS } from '../../types/rbac';

interface AccessRestrictedProps {
  featureKey: FeatureKey;
  featureName?: string;
  onNavigateHome?: () => void;
}

export const AccessRestricted: React.FC<AccessRestrictedProps> = ({
  featureKey,
  featureName,
  onNavigateHome,
}) => {
  const { currentUser, users, switchUser } = useAuth();

  const featureDef = SYSTEM_FEATURES.find((f) => f.key === featureKey);
  const roleConfig = ROLE_CONFIGS[currentUser.role];

  // Find admin user for contact / quick demo switch
  const adminUser = users.find((u) => u.role === 'admin') || users[0];

  return (
    <div
      id="access-restricted-screen"
      className="flex-1 flex flex-col items-center justify-center p-6 bg-[#050505] text-[#F8FAFC] font-mono select-none"
    >
      <div className="w-full max-w-lg bg-[#111114] border border-rose-500/40 rounded-lg p-6 space-y-5 shadow-2xl relative overflow-hidden">
        {/* Top Accent Line */}
        <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-rose-600 via-amber-500 to-rose-600" />

        {/* Lock Icon & Header */}
        <div className="flex items-start gap-4">
          <div className="w-12 h-12 rounded bg-rose-950/60 border border-rose-800/80 flex items-center justify-center text-rose-400 shrink-0">
            <Lock className="w-6 h-6" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="px-2 py-0.5 rounded bg-rose-950/80 border border-rose-800 text-rose-300 text-[9px] font-bold uppercase tracking-wider">
                RBAC Access Restricted
              </span>
              <span className="text-[10px] text-[#64748B]">Zero-Trust Enforcement</span>
            </div>
            <h2 className="text-base font-bold text-[#F8FAFC] mt-1">
              Permission Required: {featureName || featureDef?.label || featureKey}
            </h2>
            <p className="text-[11px] text-[#94A3B8] mt-0.5">
              Your active account role is not authorized to access this feature.
            </p>
          </div>
        </div>

        {/* Active Account Breakdown */}
        <div className="p-3.5 rounded bg-[#0B0B0C] border border-[#1E293B] space-y-2 text-xs">
          <div className="flex items-center justify-between text-[11px]">
            <span className="text-[#64748B]">Current Identity:</span>
            <span className="text-[#F8FAFC] font-bold">{currentUser.name} ({currentUser.email})</span>
          </div>
          <div className="flex items-center justify-between text-[11px]">
            <span className="text-[#64748B]">Assigned Role:</span>
            <span className={`px-2 py-0.5 rounded text-[10px] font-bold border ${roleConfig?.badgeBg} ${roleConfig?.badgeText} ${roleConfig?.badgeBorder}`}>
              {roleConfig?.label.toUpperCase()}
            </span>
          </div>
          <div className="flex items-center justify-between text-[11px]">
            <span className="text-[#64748B]">Required Permission:</span>
            <code className="text-[#FFC107] bg-[#111114] px-1.5 py-0.5 rounded border border-[#1E293B] text-[10px]">
              {featureKey}
            </code>
          </div>
          {featureDef && (
            <p className="text-[10px] text-[#64748B] pt-1 border-t border-[#1E293B]">
              {featureDef.description}
            </p>
          )}
        </div>

        {/* Action Options */}
        <div className="space-y-2.5 pt-1">
          <div className="text-[10px] text-[#94A3B8] flex items-center gap-1.5">
            <ShieldAlert className="w-3.5 h-3.5 text-[#FFC107]" />
            <span>Only a <b>System Admin</b> can grant feature access in User Management.</span>
          </div>

          <div className="flex flex-col sm:flex-row items-center gap-2">
            {currentUser.role !== 'admin' && (
              <button
                id="switch-to-admin-demo-btn"
                onClick={() => switchUser(adminUser.id)}
                className="w-full sm:w-auto flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded bg-[#FFC107] hover:bg-[#FFB300] text-black font-bold text-xs transition-colors cursor-pointer"
              >
                <KeyRound className="w-3.5 h-3.5" />
                <span>Switch to Admin ({adminUser.name})</span>
              </button>
            )}

            {onNavigateHome && (
              <button
                onClick={onNavigateHome}
                className="w-full sm:w-auto px-3 py-2 rounded bg-[#0B0B0C] border border-[#1E293B] hover:bg-[#1E293B] text-[#94A3B8] hover:text-[#F8FAFC] text-xs transition-colors cursor-pointer"
              >
                Return to UNS Tree
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

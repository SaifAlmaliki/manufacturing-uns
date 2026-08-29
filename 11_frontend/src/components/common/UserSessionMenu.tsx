import React, { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  User,
  Shield,
  CheckCircle2,
  ChevronDown,
  Users,
  KeyRound,
  Lock,
  LogOut,
  UserCheck,
  Home,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { useUNS } from '../../context/UNSContext';
import { ROLE_CONFIGS, SYSTEM_FEATURES, FeatureKey } from '../../types/rbac';

export const UserSessionMenu: React.FC = () => {
  const navigate = useNavigate();
  const { currentUser, users, switchUser, isAdmin, hasPermission, logout } = useAuth();
  const { setActiveTab } = useUNS();
  const [isOpen, setIsOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Close when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const roleConfig = ROLE_CONFIGS[currentUser.role] || ROLE_CONFIGS.viewer;

  return (
    <div className="relative" ref={menuRef}>
      {/* Trigger Button */}
      <button
        id="user-session-trigger"
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 px-2.5 py-1 rounded-md bg-[#F8FAFC] dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] hover:border-amber-400 dark:hover:border-[#334155] transition-all cursor-pointer select-none shadow-xs"
        title="Active User Identity & RBAC Role Switcher"
      >
        <div className={`w-5 h-5 rounded-full ${currentUser.avatarColor || 'bg-amber-400 dark:bg-[#FFC107]'} flex items-center justify-center text-[10px] font-bold text-slate-950`}>
          {currentUser.name.charAt(0).toUpperCase()}
        </div>
        <div className="hidden lg:flex flex-col text-left leading-none">
          <span className="font-bold text-[11px] text-[#0F172A] dark:text-[#F8FAFC] truncate max-w-[120px] font-mono">
            {currentUser.name}
          </span>
          <span className={`text-[9px] font-mono ${roleConfig.badgeText} uppercase font-semibold`}>
            {roleConfig.label}
          </span>
        </div>
        <ChevronDown className="w-3 h-3 text-[#64748B]" />
      </button>

      {/* Popover Dropdown */}
      {isOpen && (
        <div
          id="user-session-dropdown"
          className="absolute right-0 mt-2 w-80 bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] rounded-lg shadow-xl z-50 p-3 font-mono text-xs animate-in fade-in zoom-in-95 duration-150"
        >
          {/* Header Card */}
          <div className="p-2.5 rounded bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#E2E8F0] dark:border-[#1E293B] mb-2.5 space-y-1.5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className={`w-7 h-7 rounded-full ${currentUser.avatarColor || 'bg-amber-400 dark:bg-[#FFC107]'} flex items-center justify-center text-xs font-bold text-slate-950`}>
                  {currentUser.name.charAt(0).toUpperCase()}
                </div>
                <div>
                  <div className="font-bold text-[#0F172A] dark:text-[#F8FAFC] text-xs">{currentUser.name}</div>
                  <div className="text-[10px] text-[#64748B]">{currentUser.email}</div>
                </div>
              </div>
              <span className={`px-2 py-0.5 rounded text-[9px] font-bold border ${roleConfig.badgeBg} ${roleConfig.badgeText} ${roleConfig.badgeBorder}`}>
                {roleConfig.label.toUpperCase()}
              </span>
            </div>
            <div className="text-[9px] text-[#475569] dark:text-[#94A3B8] pt-1 border-t border-[#E2E8F0] dark:border-[#1E293B] flex items-center justify-between">
              <span>Plant / Dept:</span>
              <span className="text-[#0F172A] dark:text-[#F8FAFC] font-semibold truncate max-w-[170px]">{currentUser.department}</span>
            </div>
          </div>

          {/* Quick RBAC Action */}
          {isAdmin && (
            <button
              id="goto-user-management-btn"
              onClick={() => {
                setActiveTab('users');
                setIsOpen(false);
              }}
              className="w-full flex items-center justify-between p-2 mb-2.5 rounded bg-amber-50 dark:bg-[#FFC107]/10 border border-amber-300 dark:border-[#FFC107]/30 hover:bg-amber-100 dark:hover:bg-[#FFC107]/20 text-amber-900 dark:text-[#FFC107] transition-colors cursor-pointer text-left font-semibold"
            >
              <div className="flex items-center gap-2">
                <Shield className="w-3.5 h-3.5 text-amber-600 dark:text-[#FFC107]" />
                <span className="font-bold text-[11px]">User Management &amp; RBAC</span>
              </div>
              <span className="text-[9px] uppercase px-1.5 py-0.5 rounded bg-amber-400 dark:bg-[#FFC107] text-slate-950 font-bold">Admin</span>
            </button>
          )}

          {/* Switch Active User / Test RBAC Roles */}
          <div className="space-y-1">
            <div className="flex items-center justify-between text-[9px] uppercase tracking-wider text-[#64748B] px-1 pb-1 font-semibold">
              <span>Switch Identity (Simulate RBAC)</span>
              <span>{users.length} Users</span>
            </div>

            <div className="max-h-48 overflow-y-auto space-y-1 pr-1 scrollbar-thin scrollbar-thumb-slate-300 dark:scrollbar-thumb-[#1E293B]">
              {users.map((u) => {
                const isSelected = u.id === currentUser.id;
                const userRole = ROLE_CONFIGS[u.role] || ROLE_CONFIGS.viewer;
                return (
                  <button
                    key={u.id}
                    onClick={() => {
                      switchUser(u.id);
                      setIsOpen(false);
                    }}
                    className={`w-full flex items-center justify-between p-1.5 rounded-md text-left transition-colors cursor-pointer ${
                      isSelected
                        ? 'bg-amber-50 dark:bg-[#1E293B] border border-amber-400 dark:border-[#FFC107] text-[#0F172A] dark:text-[#F8FAFC]'
                        : 'bg-white dark:bg-[#0B0B0C] border border-[#E2E8F0] dark:border-transparent hover:border-slate-300 dark:hover:border-[#1E293B] text-[#475569] dark:text-[#94A3B8] hover:text-[#0F172A] dark:hover:text-[#F8FAFC]'
                    }`}
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <div className={`w-5 h-5 rounded-full ${u.avatarColor || 'bg-slate-600'} flex items-center justify-center text-[10px] font-bold text-slate-950 shrink-0`}>
                        {u.name.charAt(0).toUpperCase()}
                      </div>
                      <div className="truncate">
                        <div className="font-semibold text-[11px] truncate flex items-center gap-1.5">
                          <span>{u.name}</span>
                          {isSelected && <CheckCircle2 className="w-3 h-3 text-amber-600 dark:text-[#FFC107]" />}
                        </div>
                        <div className="text-[9px] text-[#64748B] truncate">{u.email}</div>
                      </div>
                    </div>

                    <span className={`text-[8px] font-bold px-1.5 py-0.5 rounded shrink-0 border ${userRole.badgeBg} ${userRole.badgeText} ${userRole.badgeBorder}`}>
                      {u.role.toUpperCase()}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Current Active Permissions Snapshot */}
          <div className="pt-2 mt-2 border-t border-[#E2E8F0] dark:border-[#1E293B]">
            <div className="text-[9px] uppercase tracking-wider text-[#64748B] mb-1.5 font-semibold">
              Current Granted Features:
            </div>
            <div className="flex flex-wrap gap-1">
              {SYSTEM_FEATURES.map((feat) => {
                const allowed = hasPermission(feat.key);
                return (
                  <span
                    key={feat.key}
                    className={`px-1.5 py-0.5 rounded text-[8px] flex items-center gap-1 border ${
                      allowed
                        ? 'bg-emerald-50 dark:bg-emerald-950/40 border-emerald-300 dark:border-emerald-800/40 text-emerald-700 dark:text-emerald-400 font-medium'
                        : 'bg-slate-100 dark:bg-[#0B0B0C] border-slate-200 dark:border-[#1E293B] text-slate-400 dark:text-[#475569] line-through'
                    }`}
                  >
                    {allowed ? <UserCheck className="w-2.5 h-2.5" /> : <Lock className="w-2.5 h-2.5" />}
                    <span>{feat.label}</span>
                  </span>
                );
              })}
            </div>
          </div>

          {/* Footer Actions: Landing Page & Sign Out */}
          <div className="pt-2.5 mt-2.5 border-t border-[#E2E8F0] dark:border-[#1E293B] flex items-center gap-2">
            <button
              onClick={() => {
                setIsOpen(false);
                navigate('/');
              }}
              className="flex-1 flex items-center justify-center gap-1.5 py-1.5 px-2 rounded bg-slate-100 dark:bg-[#1E293B] hover:bg-slate-200 dark:hover:bg-[#334155] text-slate-700 dark:text-slate-300 text-[11px] font-semibold transition-colors cursor-pointer"
            >
              <Home className="w-3 h-3" />
              <span>Landing Page</span>
            </button>

            <button
              onClick={() => {
                logout();
                setIsOpen(false);
                navigate('/');
              }}
              className="flex-1 flex items-center justify-center gap-1.5 py-1.5 px-2 rounded bg-rose-50 dark:bg-rose-950/30 hover:bg-rose-100 dark:hover:bg-rose-900/40 text-rose-600 dark:text-rose-400 border border-rose-200 dark:border-rose-800/40 text-[11px] font-semibold transition-colors cursor-pointer"
            >
              <LogOut className="w-3 h-3" />
              <span>Sign Out</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

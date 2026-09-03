import React, { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Shield,
  CheckCircle2,
  ChevronDown,
  Lock,
  LogOut,
  UserCheck,
  Home,
  Sun,
  Moon,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { useUNS } from '../../context/UNSContext';
import { useTheme } from '../../context/ThemeContext';
import { ROLE_CONFIGS, SYSTEM_FEATURES } from '../../types/rbac';

interface UserSessionMenuProps {
  variant?: 'header' | 'sidebar' | 'compact';
}

export const UserSessionMenu: React.FC<UserSessionMenuProps> = ({ variant = 'header' }) => {
  const navigate = useNavigate();
  const { currentUser, users, switchUser, isAdmin, hasPermission, logout } = useAuth();
  const { setActiveTab } = useUNS();
  const { isDark, toggleTheme } = useTheme();
  const [isOpen, setIsOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

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
  const isSidebarStyle = variant === 'sidebar' || variant === 'compact';

  return (
    <div className={`relative ${variant === 'compact' ? 'w-full flex justify-center' : 'w-full'}`} ref={menuRef}>
      <button
        id="user-session-trigger"
        onClick={() => setIsOpen(!isOpen)}
        className={`flex w-full items-center gap-3 rounded-xl transition-colors cursor-pointer select-none ${
          isSidebarStyle
            ? 'p-2 hover:bg-zinc-800/60'
            : 'gap-2 px-2.5 py-1 rounded-md bg-zinc-900 border border-zinc-800 hover:border-zinc-700'
        }`}
        title="Account menu"
        aria-label="Account menu"
        aria-expanded={isOpen}
      >
        <div
          className={`flex shrink-0 items-center justify-center rounded-full font-semibold text-zinc-950 ${
            currentUser.avatarColor || 'bg-[#FF7A00]'
          } ${variant === 'compact' ? 'size-9 text-sm' : 'size-9 text-sm'}`}
        >
          {currentUser.name.charAt(0).toUpperCase()}
        </div>

        {variant !== 'compact' && (
          <>
            <div className="min-w-0 flex-1 text-left">
              <div className="truncate text-sm font-medium text-zinc-100">{currentUser.name}</div>
              <div className="truncate text-xs text-zinc-500">{currentUser.email}</div>
            </div>
            <ChevronDown className={`size-4 shrink-0 text-zinc-500 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
          </>
        )}
      </button>

      {isOpen && (
        <div
          id="user-session-dropdown"
          className={`absolute z-50 w-72 rounded-2xl border border-zinc-800 bg-[#18181b] p-3 shadow-2xl text-sm ${
            isSidebarStyle ? 'bottom-full left-0 mb-2' : 'right-0 top-full mt-2'
          }`}
        >
          <div className="mb-3 rounded-xl border border-zinc-800 bg-zinc-900/60 p-3">
            <div className="flex items-center gap-3">
              <div
                className={`flex size-10 items-center justify-center rounded-full font-bold text-zinc-950 ${
                  currentUser.avatarColor || 'bg-[#FF7A00]'
                }`}
              >
                {currentUser.name.charAt(0).toUpperCase()}
              </div>
              <div className="min-w-0">
                <div className="truncate font-semibold text-zinc-100">{currentUser.name}</div>
                <div className="truncate text-xs text-zinc-500">{currentUser.email}</div>
                <span className={`mt-1 inline-block rounded-md px-2 py-0.5 text-[10px] font-semibold uppercase ${roleConfig.badgeBg} ${roleConfig.badgeText}`}>
                  {roleConfig.label}
                </span>
              </div>
            </div>
          </div>

          {isAdmin && (
            <button
              id="goto-user-management-btn"
              onClick={() => {
                setActiveTab('users');
                setIsOpen(false);
                navigate('/users');
              }}
              className="mb-2 flex w-full items-center gap-2 rounded-xl border border-[#FF7A00]/30 bg-[#FF7A00]/10 p-2.5 text-left text-sm font-medium text-[#FF7A00] transition-colors hover:bg-[#FF7A00]/20"
            >
              <Shield className="size-4" />
              User Management
            </button>
          )}

          <button
            onClick={toggleTheme}
            className="mb-2 flex w-full items-center gap-2 rounded-xl p-2.5 text-left text-sm text-zinc-400 transition-colors hover:bg-zinc-800 hover:text-zinc-100"
          >
            {isDark ? <Sun className="size-4" /> : <Moon className="size-4" />}
            Switch to {isDark ? 'light' : 'dark'} mode
          </button>

          <div className="mb-2 max-h-40 space-y-1 overflow-y-auto">
            <div className="px-1 pb-1 text-[10px] font-medium uppercase tracking-wider text-zinc-600">
              Switch user
            </div>
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
                  className={`flex w-full items-center gap-2 rounded-lg p-2 text-left transition-colors ${
                    isSelected
                      ? 'bg-[#FF7A00]/15 text-zinc-100'
                      : 'text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100'
                  }`}
                >
                  <div
                    className={`flex size-7 shrink-0 items-center justify-center rounded-full text-xs font-bold text-zinc-950 ${
                      u.avatarColor || 'bg-zinc-600'
                    }`}
                  >
                    {u.name.charAt(0).toUpperCase()}
                  </div>
                  <div className="min-w-0 flex-1 truncate">
                    <div className="flex items-center gap-1 text-sm font-medium">
                      {u.name}
                      {isSelected && <CheckCircle2 className="size-3 text-[#FF7A00]" />}
                    </div>
                    <div className="truncate text-xs text-zinc-500">{userRole.label}</div>
                  </div>
                </button>
              );
            })}
          </div>

          <div className="mb-2 border-t border-zinc-800 pt-2">
            <div className="mb-1.5 px-1 text-[10px] font-medium uppercase tracking-wider text-zinc-600">
              Permissions
            </div>
            <div className="flex flex-wrap gap-1">
              {SYSTEM_FEATURES.map((feat) => {
                const allowed = hasPermission(feat.key);
                return (
                  <span
                    key={feat.key}
                    className={`flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] ${
                      allowed
                        ? 'bg-emerald-500/10 text-emerald-400'
                        : 'bg-zinc-800 text-zinc-600 line-through'
                    }`}
                  >
                    {allowed ? <UserCheck className="size-2.5" /> : <Lock className="size-2.5" />}
                    {feat.label}
                  </span>
                );
              })}
            </div>
          </div>

          <div className="flex gap-2 border-t border-zinc-800 pt-2">
            <button
              onClick={() => {
                setIsOpen(false);
                navigate('/');
              }}
              className="flex flex-1 items-center justify-center gap-1.5 rounded-xl bg-zinc-800 py-2 text-xs font-medium text-zinc-300 transition-colors hover:bg-zinc-700"
            >
              <Home className="size-3.5" />
              Home
            </button>
            <button
              onClick={() => {
                logout();
                setIsOpen(false);
                navigate('/');
              }}
              className="flex flex-1 items-center justify-center gap-1.5 rounded-xl bg-red-500/10 py-2 text-xs font-medium text-red-400 transition-colors hover:bg-red-500/20"
            >
              <LogOut className="size-3.5" />
              Sign out
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

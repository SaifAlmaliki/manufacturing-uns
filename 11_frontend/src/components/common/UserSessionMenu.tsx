import React, { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Shield,
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
  const { currentUser, isAdmin, hasPermission, logout } = useAuth();
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

  const isSidebarStyle = variant === 'sidebar' || variant === 'compact';
  const isHeader = variant === 'header';

  if (!currentUser) {
    return null;
  }

  const roleConfig = ROLE_CONFIGS[currentUser.role] || ROLE_CONFIGS.viewer;

  return (
    <div
      className={`relative ${
        variant === 'compact' ? 'flex w-full justify-center' : isHeader ? 'w-auto max-w-[12rem]' : 'w-full'
      }`}
      ref={menuRef}
    >
      <button
        id="user-session-trigger"
        onClick={() => setIsOpen(!isOpen)}
        className={`flex items-center rounded-xl transition-colors cursor-pointer select-none ${
          isSidebarStyle
            ? 'w-full gap-3 p-2 hover:bg-muted'
            : 'w-auto max-w-full gap-2 rounded-md border border-border bg-surface px-2.5 py-1 hover:bg-muted'
        }`}
        title={currentUser.name}
        aria-label={`${currentUser.name}, account menu`}
        aria-expanded={isOpen}
      >
        <div
          className={`flex shrink-0 items-center justify-center rounded-full font-semibold text-zinc-950 ${
            currentUser.avatarColor || 'bg-[#FF7A00]'
          } ${isHeader ? 'size-7 text-xs' : 'size-9 text-sm'}`}
        >
          {currentUser.name.charAt(0).toUpperCase()}
        </div>

        {variant !== 'compact' && (
          <>
            <div className={`min-w-0 text-left ${isHeader ? '' : 'flex-1'}`}>
              <div className="truncate text-sm font-medium text-foreground">{currentUser.name}</div>
              {variant === 'sidebar' && (
                <div className="truncate text-xs text-muted-foreground">{currentUser.email}</div>
              )}
            </div>
            <ChevronDown className={`size-4 shrink-0 text-muted-foreground transition-transform ${isOpen ? 'rotate-180' : ''}`} />
          </>
        )}
      </button>

      {isOpen && (
        <div
          id="user-session-dropdown"
          className={`absolute z-50 w-72 rounded-2xl border border-border bg-popover p-3 shadow-2xl text-sm ${
            isSidebarStyle ? 'bottom-full left-0 mb-2' : 'right-0 top-full mt-2'
          }`}
        >
          <div className="mb-3 rounded-xl border border-border bg-muted/60 p-3">
            <div className="flex items-center gap-3">
              <div
                className={`flex size-10 items-center justify-center rounded-full font-bold text-zinc-950 ${
                  currentUser.avatarColor || 'bg-[#FF7A00]'
                }`}
              >
                {currentUser.name.charAt(0).toUpperCase()}
              </div>
              <div className="min-w-0">
                <div className="truncate font-semibold text-foreground">{currentUser.name}</div>
                <div className="truncate text-xs text-muted-foreground">{currentUser.email}</div>
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
            className="mb-2 flex w-full items-center gap-2 rounded-xl p-2.5 text-left text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            {isDark ? <Sun className="size-4" /> : <Moon className="size-4" />}
            Switch to {isDark ? 'light' : 'dark'} mode
          </button>

          <div className="mb-2 border-t border-border pt-2">
            <div className="mb-1.5 px-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
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
                        ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400'
                        : 'bg-muted text-muted-foreground line-through'
                    }`}
                  >
                    {allowed ? <UserCheck className="size-2.5" /> : <Lock className="size-2.5" />}
                    {feat.label}
                  </span>
                );
              })}
            </div>
          </div>

          <div className="flex gap-2 border-t border-border pt-2">
            <button
              onClick={() => {
                setIsOpen(false);
                navigate('/');
              }}
              className="flex flex-1 items-center justify-center gap-1.5 rounded-xl bg-muted py-2 text-xs font-medium text-foreground transition-colors hover:bg-muted/80"
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

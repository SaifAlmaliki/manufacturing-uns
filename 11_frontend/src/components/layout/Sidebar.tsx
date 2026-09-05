import React, { useState } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import {
  LayoutDashboard,
  Layers,
  Bell,
  Search,
  Radio,
  Workflow,
  Activity,
  Shield,
  FlaskConical,
  Network,
  Cable,
  Lock,
  X,
  ChevronLeft,
  ChevronRight,
  Command,
} from 'lucide-react';
import { useUNS } from '../../context/UNSContext';
import { useAuth } from '../../context/AuthContext';
import { useAlarms } from '../../context/AlarmContext';
import { FeatureKey } from '../../types/rbac';
import { UserSessionMenu } from '../common/UserSessionMenu';

interface SidebarProps {
  isCollapsed: boolean;
  onToggleCollapse: () => void;
  isMobileOpen: boolean;
  onCloseMobile: () => void;
  onOpenBookmarks: () => void;
  onOpenStaleDrawer: () => void;
}

interface NavItem {
  to: string;
  tabId: string;
  label: string;
  icon: React.FC<{ className?: string }>;
  featureKey: FeatureKey;
  adminOnly?: boolean;
}

const MAIN_MENU: NavItem[] = [
  { to: '/dashboard', tabId: 'home', label: 'Dashboard', icon: LayoutDashboard, featureKey: 'uns_tree' },
  { to: '/condition-monitoring', tabId: 'home', label: 'Condition Monitoring', icon: Layers, featureKey: 'uns_tree' },
  { to: '/alerts', tabId: 'alarms', label: 'Alarms', icon: Bell, featureKey: 'alarms' },
  { to: '/historian', tabId: 'explore', label: 'Historian', icon: Search, featureKey: 'historian' },
  { to: '/sparkplug', tabId: 'sparkplug', label: 'Sparkplug B', icon: Radio, featureKey: 'sparkplug' },
  { to: '/streams', tabId: 'streams', label: 'Streams', icon: Workflow, featureKey: 'streams' },
];

const PLATFORM_MENU: NavItem[] = [
  { to: '/system', tabId: 'system', label: 'System Health', icon: Activity, featureKey: 'system_ops' },
  { to: '/simulator', tabId: 'simulator', label: 'Simulator', icon: FlaskConical, featureKey: 'simulator_ops' },
  { to: '/connectivity', tabId: 'connectivity', label: 'Assets & Connectivity', icon: Cable, featureKey: 'connectivity' },
  { to: '/hierarchy', tabId: 'hierarchy', label: 'Plant hierarchy', icon: Network, featureKey: 'settings_edit', adminOnly: true },
  { to: '/users', tabId: 'users', label: 'Users & Access', icon: Shield, featureKey: 'user_management', adminOnly: true },
];

export const Sidebar: React.FC<SidebarProps> = ({
  isCollapsed,
  onToggleCollapse,
  isMobileOpen,
  onCloseMobile,
}) => {
  const location = useLocation();
  const navigate = useNavigate();
  const { settings, health } = useUNS();
  const { canAccessTab, isAdmin } = useAuth();
  const { myUnacknowledgedCount } = useAlarms();
  const [searchQuery, setSearchQuery] = useState('');

  const isActive = (item: NavItem) => {
    if (item.to === '/dashboard') {
      return location.pathname === '/dashboard';
    }
    if (item.to === '/condition-monitoring') {
      return location.pathname === '/condition-monitoring' || location.pathname.startsWith('/condition-monitoring/');
    }
    if (item.to === '/tree') {
      return location.pathname === '/tree';
    }
    return location.pathname === item.to || location.pathname.startsWith(`${item.to}/`);
  };

  const filteredMain = MAIN_MENU.filter((item) => {
    if (!searchQuery) return true;
    return item.label.toLowerCase().includes(searchQuery.toLowerCase());
  });

  const filteredPlatform = PLATFORM_MENU.filter((item) => {
    if (item.adminOnly && !isAdmin) return false;
    if (!searchQuery) return true;
    return item.label.toLowerCase().includes(searchQuery.toLowerCase());
  });

  const renderNavItem = (item: NavItem) => {
    const Icon = item.icon;
    const access = canAccessTab(item.tabId);
    const locked = !access.allowed;
    const active = isActive(item);
    const showAlarmDot = item.tabId === 'alarms' && myUnacknowledgedCount > 0;

    const handleClick = (e: React.MouseEvent) => {
      if (locked) {
        e.preventDefault();
        return;
      }
      onCloseMobile();
    };

    return (
      <NavLink
        key={`${item.to}-${item.label}`}
        to={locked ? '#' : item.to}
        onClick={handleClick}
        className={`group relative flex items-center gap-3 rounded-md px-3 py-2.5 text-sm font-medium transition-colors ${
          active
            ? 'bg-[#FF7A00] text-white'
            : locked
              ? 'text-muted-foreground cursor-not-allowed'
              : 'text-muted-foreground hover:bg-muted hover:text-foreground'
        } ${isCollapsed ? 'justify-center px-2.5' : ''}`}
        title={isCollapsed ? item.label : undefined}
      >
        <Icon className={`size-[18px] shrink-0 ${active ? 'text-white' : locked ? 'text-muted-foreground/60' : 'text-muted-foreground group-hover:text-foreground'}`} />
        {!isCollapsed && (
          <>
            <span className="flex-1 truncate">{item.label}</span>
            {locked && <Lock className="size-3.5 text-muted-foreground/60" />}
            {showAlarmDot && !locked && (
              <span className="flex size-5 items-center justify-center rounded-full bg-red-500 text-[10px] font-semibold text-white tabular-nums">
                {myUnacknowledgedCount > 9 ? '9+' : myUnacknowledgedCount}
              </span>
            )}
          </>
        )}
        {isCollapsed && showAlarmDot && !locked && (
          <span className="absolute right-1.5 top-1.5 size-2 rounded-full bg-red-500" />
        )}
      </NavLink>
    );
  };

  const platformStatusDot =
    health.status === 'LIVE'
      ? 'bg-emerald-500'
      : health.status === 'DEGRADED'
        ? 'bg-amber-500'
        : 'bg-red-500';

  const platformStatusLabel =
    health.status === 'LIVE'
      ? 'Connected'
      : health.status === 'DEGRADED'
        ? 'Degraded'
        : health.status === 'DOWN'
          ? 'Down'
          : health.status;

  const platformStatusTitle =
    health.status === 'LIVE'
      ? 'Platform connected — open System Health'
      : `Platform ${platformStatusLabel.toLowerCase()} — open System Health`;

  const sidebarContent = (
    <aside
      id="application-left-menu"
      className={`flex h-full flex-col select-none border-r border-border bg-surface transition-all duration-200 ${
        isCollapsed ? 'w-[72px]' : 'w-[260px]'
      }`}
    >
      {/* Brand */}
      <div className="flex h-16 shrink-0 items-center justify-between border-b border-border px-4">
        <div className={`flex items-center gap-3 min-w-0 ${isCollapsed ? 'justify-center w-full' : ''}`}>
          <div className="flex size-9 shrink-0 items-center justify-center rounded-md bg-[#FF7A00]">
            <span className="font-heading text-lg font-bold text-[#140800]">U</span>
          </div>
          {!isCollapsed && (
            <div className="min-w-0 leading-tight">
              <div className="font-heading truncate text-[15px] font-semibold tracking-tight text-foreground">UNS Console</div>
              <div className="truncate text-xs text-muted-foreground">
                {settings.organization || 'Smart Manufacturing'}
              </div>
            </div>
          )}
        </div>
        {!isCollapsed && (
          <button
            onClick={onCloseMobile}
            className="lg:hidden rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
            aria-label="Close navigation"
          >
            <X className="size-4" />
          </button>
        )}
      </div>

      {/* Search */}
      {!isCollapsed && (
        <div className="shrink-0 px-3 pt-4 pb-2">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <input
              type="search"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search menu..."
              className="w-full rounded-md border border-border bg-background py-2.5 pl-9 pr-12 text-sm text-foreground placeholder:text-muted-foreground focus:border-[#FF7A00]/50 focus:outline-none focus:ring-1 focus:ring-[#FF7A00]/30"
            />
            <kbd className="pointer-events-none absolute right-2.5 top-1/2 hidden -translate-y-1/2 items-center gap-0.5 rounded border border-border bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground sm:flex">
              <Command className="size-2.5" />K
            </kbd>
          </div>
        </div>
      )}

      {/* Navigation */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden px-3 py-2 space-y-6">
        <div className="space-y-1">
          {!isCollapsed && (
            <div className="px-2 pb-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Main Menu
            </div>
          )}
          {filteredMain.map(renderNavItem)}
        </div>

        {filteredPlatform.length > 0 && (
          <div className="space-y-1">
            {!isCollapsed && (
              <div className="px-2 pb-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                Platform
              </div>
            )}
            {filteredPlatform.map(renderNavItem)}
          </div>
        )}
      </div>

      {/* Platform status — compact */}
      <div className={`shrink-0 px-3 pb-2 ${isCollapsed ? 'flex justify-center' : ''}`}>
        <button
          type="button"
          onClick={() => {
            navigate('/system');
            onCloseMobile();
          }}
          title={platformStatusTitle}
          aria-label={platformStatusTitle}
          className={`flex items-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground ${
            isCollapsed ? 'relative p-2.5' : 'w-full gap-2.5 px-3 py-2'
          }`}
        >
          <span className="relative shrink-0">
            <Activity className="size-[18px]" />
            <span
              className={`absolute -right-0.5 -top-0.5 size-2 rounded-full ring-2 ring-surface ${platformStatusDot}`}
            />
          </span>
          {!isCollapsed && (
            <span className="truncate text-xs text-muted-foreground">{platformStatusLabel}</span>
          )}
        </button>
      </div>

      {/* Collapse toggle (desktop) */}
      <div className="hidden shrink-0 border-t border-border lg:block">
        <button
          onClick={onToggleCollapse}
          className="flex w-full items-center justify-center gap-2 py-2.5 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          aria-label={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {isCollapsed ? <ChevronRight className="size-4" /> : <ChevronLeft className="size-4" />}
          {!isCollapsed && <span>Collapse</span>}
        </button>
      </div>

      {/* User profile */}
      <div className={`shrink-0 border-t border-border p-3 ${isCollapsed ? 'flex justify-center' : ''}`}>
        <UserSessionMenu variant={isCollapsed ? 'compact' : 'sidebar'} />
      </div>
    </aside>
  );

  return (
    <>
      <div className="hidden h-full shrink-0 lg:block">{sidebarContent}</div>

      {isMobileOpen && (
        <div id="mobile-sidebar-drawer" className="fixed inset-0 z-50 flex lg:hidden" role="dialog" aria-modal="true">
          <div className="fixed inset-0 bg-black/70" onClick={onCloseMobile} />
          <div className="relative z-10 h-full w-[280px] max-w-[85vw] shadow-2xl">{sidebarContent}</div>
        </div>
      )}
    </>
  );
};

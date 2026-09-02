import React from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import {
  Layers,
  Search,
  Radio,
  Workflow,
  Activity,
  Shield,
  Lock,
  ChevronLeft,
  ChevronRight,
  Database,
  Server,
  Zap,
  Bookmark,
  AlertTriangle,
  X,
  Bell,
  FlaskConical,
} from 'lucide-react';
import { useUNS } from '../../context/UNSContext';
import { useAuth } from '../../context/AuthContext';
import { useAlarms } from '../../context/AlarmContext';
import { FeatureKey } from '../../types/rbac';

interface SidebarProps {
  isCollapsed: boolean;
  onToggleCollapse: () => void;
  isMobileOpen: boolean;
  onCloseMobile: () => void;
  onOpenBookmarks: () => void;
  onOpenStaleDrawer: () => void;
}

interface NavSectionItem {
  to: string;
  tabId: string;
  label: string;
  shortLabel: string;
  icon: React.FC<{ className?: string }>;
  description: string;
  featureKey: FeatureKey;
  badge?: string | number;
  adminOnly?: boolean;
}

export const Sidebar: React.FC<SidebarProps> = ({
  isCollapsed,
  onToggleCollapse,
  isMobileOpen,
  onCloseMobile,
  onOpenBookmarks,
  onOpenStaleDrawer,
}) => {
  const location = useLocation();
  const { allLoadedNodes, bookmarks, staleNodesCount, health, settings } = useUNS();
  const { canAccessTab, currentUser, isAdmin } = useAuth();
  const { myUnacknowledgedCount } = useAlarms();

  const coreNavItems: NavSectionItem[] = [
    {
      to: '/tree',
      tabId: 'home',
      label: 'UNS Tree & Graph',
      shortLabel: 'UNS Tree',
      icon: Layers,
      description: 'ISA-95 Namespace Hierarchy',
      featureKey: 'uns_tree',
      badge: allLoadedNodes.length > 0 ? allLoadedNodes.length : undefined,
    },
    {
      to: '/alerts',
      tabId: 'alarms',
      label: 'Alarm Management',
      shortLabel: 'Alarms',
      icon: Bell,
      description: 'Role-Based Alert Rules',
      featureKey: 'alarms',
      badge: myUnacknowledgedCount > 0 ? myUnacknowledgedCount : undefined,
    },
    {
      to: '/historian',
      tabId: 'explore',
      label: 'Historian Explorer',
      shortLabel: 'Historian',
      icon: Search,
      description: 'TimescaleDB Historic Events',
      featureKey: 'historian',
      badge: 'Timescale',
    },
    {
      to: '/sparkplug',
      tabId: 'sparkplug',
      label: 'Sparkplug B Decoder',
      shortLabel: 'Sparkplug B',
      icon: Radio,
      description: 'Edge Protobuf & Metrics',
      featureKey: 'sparkplug',
      badge: 'v1.0',
    },
    {
      to: '/streams',
      tabId: 'streams',
      label: 'Kafka Event Streams',
      shortLabel: 'Kafka',
      icon: Workflow,
      description: 'Live Topic Streaming',
      featureKey: 'streams',
      badge: 'Live',
    },
  ];

  const opsNavItems: NavSectionItem[] = [
    {
      to: '/system',
      tabId: 'system',
      label: 'System Operations',
      shortLabel: 'System Ops',
      icon: Activity,
      description: 'Grafana: platform, process, OEE',
      featureKey: 'system_ops',
    },
    {
      to: '/simulator',
      tabId: 'simulator',
      label: 'Simulator Control',
      shortLabel: 'Simulator',
      icon: FlaskConical,
      description: 'Synthetic Plant Data Generator',
      featureKey: 'simulator_ops',
      badge: 'SIM',
    },
    {
      to: '/users',
      tabId: 'users',
      label: 'Users & RBAC Console',
      shortLabel: 'Users & RBAC',
      icon: Shield,
      description: 'Role-Based Access Control',
      featureKey: 'user_management',
      badge: 'ADMIN',
      adminOnly: true,
    },
  ];

  const renderNavLink = (item: NavSectionItem) => {
    const Icon = item.icon;
    const access = canAccessTab(item.tabId);
    const isLocked = !access.allowed;
    const isActive = location.pathname === item.to || (item.to === '/tree' && location.pathname === '/');

    return (
      <NavLink
        key={item.to}
        to={item.to}
        onClick={onCloseMobile}
        id={`sidebar-link-${item.tabId}`}
        className={`group relative flex items-center gap-3 px-3 py-2.5 rounded-lg text-xs font-mono transition-all duration-150 cursor-pointer ${
          isActive
            ? 'bg-amber-500 dark:bg-[#FFC107] text-slate-950 dark:text-[#0B0B0C] font-bold shadow-xs'
            : isLocked
            ? 'text-slate-400 dark:text-[#64748B] hover:text-slate-600 dark:hover:text-[#94A3B8] hover:bg-slate-100 dark:hover:bg-[#1E293B]/40'
            : 'text-[#475569] dark:text-[#94A3B8] hover:text-[#0F172A] dark:hover:text-[#F8FAFC] hover:bg-slate-100 dark:hover:bg-[#1E293B]'
        } ${isCollapsed ? 'justify-center px-2' : ''}`}
        title={isCollapsed ? `${item.label} - ${item.description}` : undefined}
      >
        {/* Active Route Bar Indicator on Left Edge */}
        {isActive && (
          <div className="absolute left-0 top-1.5 bottom-1.5 w-1 bg-slate-950 dark:bg-[#0B0B0C] rounded-r" />
        )}

        <div className="relative shrink-0 flex items-center justify-center">
          <Icon
            className={`w-4 h-4 transition-transform group-hover:scale-110 ${
              isActive ? 'text-slate-950 dark:text-[#0B0B0C]' : isLocked ? 'text-slate-400 dark:text-[#475569]' : 'text-amber-600 dark:text-[#FFC107]'
            }`}
          />
          {isLocked && (
            <div className="absolute -top-1 -right-1 bg-white dark:bg-[#0B0B0C] rounded-full p-0.5 border border-rose-300 dark:border-rose-600/50">
              <Lock className="w-2.5 h-2.5 text-rose-500 dark:text-rose-400" />
            </div>
          )}
        </div>

        {/* Text and Badges (Hidden when desktop collapsed) */}
        {!isCollapsed && (
          <div className="flex-1 min-w-0 flex items-center justify-between">
            <div className="min-w-0">
              <div className="truncate font-serif font-bold tracking-tight text-[12px] leading-tight">
                {item.label}
              </div>
              <div
                className={`text-[9px] font-sans truncate transition-colors ${
                  isActive ? 'text-slate-900/80 dark:text-[#0B0B0C]/75 font-medium' : 'text-[#64748B]'
                }`}
              >
                {item.description}
              </div>
            </div>

            {item.badge && (
              <span
                className={`ml-1.5 px-1.5 py-0.5 rounded text-[9px] font-bold shrink-0 uppercase tracking-wider ${
                  isActive
                    ? 'bg-slate-950 dark:bg-[#0B0B0C] text-amber-400 dark:text-[#FFC107]'
                    : item.badge === 'ADMIN'
                    ? 'bg-rose-50 dark:bg-rose-950/80 border border-rose-200 dark:border-rose-800 text-rose-700 dark:text-rose-300'
                    : item.badge === 'Live'
                    ? 'bg-emerald-50 dark:bg-emerald-950/80 border border-emerald-200 dark:border-emerald-800 text-emerald-700 dark:text-emerald-300'
                    : 'bg-slate-100 dark:bg-[#0B0B0C] border border-[#CBD5E1] dark:border-[#1E293B] text-slate-700 dark:text-[#94A3B8]'
                }`}
              >
                {item.badge}
              </span>
            )}
          </div>
        )}

        {/* Tooltip for collapsed view */}
        {isCollapsed && (
          <div className="hidden group-hover:block absolute left-full ml-2.5 px-2.5 py-1.5 bg-white dark:bg-[#1E293B] text-[#0F172A] dark:text-[#F8FAFC] text-[11px] rounded shadow-xl whitespace-nowrap z-50 border border-[#CBD5E1] dark:border-[#334155] font-mono pointer-events-none">
            <div className="font-bold flex items-center gap-1.5">
              <span>{item.label}</span>
              {isLocked && <span className="text-rose-600 dark:text-rose-400 text-[9px]">(Locked)</span>}
            </div>
            <div className="text-[9px] text-[#64748B] dark:text-[#94A3B8]">{item.description}</div>
          </div>
        )}
      </NavLink>
    );
  };

  const sidebarContent = (
    <aside
      id="application-left-menu"
      className={`h-full flex flex-col bg-[#FFFFFF] dark:bg-[#111114] border-r border-[#E2E8F0] dark:border-[#1E293B] select-none text-xs font-mono transition-all duration-200 ${
        isCollapsed ? 'w-16' : 'w-64'
      }`}
    >
      {/* Sidebar Header / Brand */}
      <div className="h-13 border-b border-[#E2E8F0] dark:border-[#1E293B] px-3.5 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="w-6 h-6 bg-amber-500 dark:bg-[#FFC107] rounded flex items-center justify-center shadow-xs shrink-0">
            <div className="w-2.5 h-2.5 bg-slate-950 dark:bg-[#0B0B0C] rounded-full" />
          </div>

          {!isCollapsed && (
            <div className="min-w-0 leading-tight">
              <span className="font-serif font-bold tracking-tight text-sm text-[#0F172A] dark:text-[#F8FAFC] block">
                UNS<span className="text-amber-600 dark:text-[#FFC107]">CONSOLE</span>
              </span>
              <span className="text-[#64748B] text-[9px] font-sans font-normal tracking-wide block truncate">
                {settings.organization || 'IIoT Unified Namespace'}
              </span>
            </div>
          )}
        </div>

        {/* Mobile close button or Desktop collapse toggle */}
        <div className="flex items-center gap-1">
          {/* Mobile Drawer Close */}
          <button
            onClick={onCloseMobile}
            className="lg:hidden p-1 rounded hover:bg-slate-100 dark:hover:bg-[#1E293B] text-[#64748B] dark:text-[#94A3B8] hover:text-[#0F172A] dark:hover:text-[#F8FAFC] cursor-pointer"
            title="Close navigation"
          >
            <X className="w-4 h-4" />
          </button>

          {/* Desktop Collapse Rail Toggle */}
          <button
            onClick={onToggleCollapse}
            className="hidden lg:flex p-1 rounded hover:bg-slate-100 dark:hover:bg-[#1E293B] text-[#64748B] dark:text-[#94A3B8] hover:text-amber-600 dark:hover:text-[#FFC107] cursor-pointer transition-colors"
            title={isCollapsed ? 'Expand sidebar (Ctrl+[)' : 'Collapse sidebar'}
          >
            {isCollapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* Main Navigation Items */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden p-2.5 space-y-4 scrollbar-thin scrollbar-thumb-slate-300 dark:scrollbar-thumb-[#1E293B]">
        {/* Core UNS Section */}
        <div className="space-y-1">
          {!isCollapsed && (
            <div className="px-2 pb-1 text-[9px] font-bold text-[#64748B] uppercase tracking-widest flex items-center justify-between">
              <span>UNS Domain</span>
              <span className="text-[8px] bg-[#F1F5F9] dark:bg-[#1E293B] px-1.5 py-0.5 rounded text-[#475569] dark:text-[#94A3B8] border border-[#E2E8F0] dark:border-[#334155]">ISA-95</span>
            </div>
          )}
          {coreNavItems.map(renderNavLink)}
        </div>

        {/* System & Ops Section */}
        <div className="space-y-1 pt-2 border-t border-[#E2E8F0] dark:border-[#1E293B]/70">
          {!isCollapsed && (
            <div className="px-2 pb-1 text-[9px] font-bold text-[#64748B] uppercase tracking-widest">
              <span>Platform Ops</span>
            </div>
          )}
          {opsNavItems.map(renderNavLink)}
        </div>

        {/* Quick Utilities in Expanded Mode */}
        {!isCollapsed && (
          <div className="space-y-1.5 pt-2 border-t border-[#E2E8F0] dark:border-[#1E293B]/70">
            <div className="px-2 pb-1 text-[9px] font-bold text-[#64748B] uppercase tracking-widest">
              <span>Console Shortcuts</span>
            </div>

            <button
              onClick={() => {
                onOpenBookmarks();
                onCloseMobile();
              }}
              className="w-full flex items-center justify-between px-3 py-2 rounded-lg bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#E2E8F0] dark:border-[#1E293B] hover:border-amber-400 dark:hover:border-[#FFC107]/50 text-[#475569] dark:text-[#94A3B8] hover:text-[#0F172A] dark:hover:text-[#F8FAFC] transition-colors cursor-pointer text-left"
            >
              <div className="flex items-center gap-2">
                <Bookmark className="w-3.5 h-3.5 text-amber-600 dark:text-[#FFC107]" />
                <span className="text-[10px]">Saved Bookmarks</span>
              </div>
              <span className="px-1.5 py-0.5 rounded bg-[#E2E8F0] dark:bg-[#1E293B] text-amber-700 dark:text-[#FFC107] text-[9px] font-bold">
                {bookmarks.length}
              </span>
            </button>

            {staleNodesCount > 0 && (
              <button
                onClick={() => {
                  onOpenStaleDrawer();
                  onCloseMobile();
                }}
                className="w-full flex items-center justify-between px-3 py-2 rounded-lg bg-amber-50 dark:bg-amber-950/40 border border-amber-300 dark:border-amber-800/60 text-amber-800 dark:text-[#FFC107] hover:bg-amber-100 dark:hover:bg-amber-950/60 transition-colors cursor-pointer text-left"
              >
                <div className="flex items-center gap-2">
                  <AlertTriangle className="w-3.5 h-3.5 text-amber-600 dark:text-[#FFC107] animate-pulse" />
                  <span className="text-[10px]">Stale Node Alerts</span>
                </div>
                <span className="px-1.5 py-0.5 rounded bg-white dark:bg-[#0B0B0C] text-amber-800 dark:text-[#FFC107] text-[9px] font-bold border border-amber-300 dark:border-amber-700">
                  {staleNodesCount}
                </span>
              </button>
            )}
          </div>
        )}
      </div>

      {/* Subsystem Health Live Indicators Footer */}
      {!isCollapsed ? (
        <div className="p-3 bg-[#F8FAFC] dark:bg-[#0B0B0C] border-t border-[#E2E8F0] dark:border-[#1E293B] space-y-2 shrink-0">
          <div className="flex items-center justify-between text-[9px] text-[#64748B]">
            <span className="uppercase tracking-wider font-semibold">Subsystems</span>
            <span className="text-emerald-600 dark:text-[#10B981] flex items-center gap-1 font-bold">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 dark:bg-[#10B981] animate-pulse" />
              <span>GQL 8000</span>
            </span>
          </div>

          <div className="grid grid-cols-3 gap-1 text-[8px] text-center font-mono">
            <div className="px-1.5 py-1 rounded bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] text-emerald-700 dark:text-[#10B981] font-semibold">
              MQTT: ON
            </div>
            <div className="px-1.5 py-1 rounded bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] text-emerald-700 dark:text-[#10B981] font-semibold">
              NEO4J: OK
            </div>
            <div className="px-1.5 py-1 rounded bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] text-emerald-700 dark:text-[#10B981] font-semibold">
              KAFKA: ON
            </div>
          </div>

          {/* Current User Session Bar */}
          <div className="pt-1.5 border-t border-[#E2E8F0] dark:border-[#1E293B] flex items-center justify-between">
            <div className="flex items-center gap-2 min-w-0">
              <div className={`w-5 h-5 rounded-full ${currentUser.avatarColor} text-slate-950 font-bold flex items-center justify-center text-[9px] shrink-0`}>
                {currentUser.name.charAt(0)}
              </div>
              <div className="min-w-0">
                <div className="text-[10px] text-[#0F172A] dark:text-[#F8FAFC] font-semibold truncate leading-none">
                  {currentUser.name}
                </div>
                <div className="text-[8px] text-[#64748B] dark:text-[#94A3B8] uppercase truncate mt-0.5">
                  {currentUser.role}
                </div>
              </div>
            </div>
            {isAdmin && (
              <span className="px-1.5 py-0.5 rounded bg-rose-50 dark:bg-rose-950 text-rose-700 dark:text-rose-300 border border-rose-200 dark:border-rose-800 text-[8px] font-bold">
                ROOT
              </span>
            )}
          </div>
        </div>
      ) : (
        <div className="p-2 bg-[#F8FAFC] dark:bg-[#0B0B0C] border-t border-[#E2E8F0] dark:border-[#1E293B] flex flex-col items-center gap-2 shrink-0">
          <span className="w-2 h-2 rounded-full bg-emerald-500 dark:bg-[#10B981] animate-pulse" title="GraphQL Subsystem Connected" />
          <div className={`w-6 h-6 rounded-full ${currentUser.avatarColor} text-slate-950 font-bold flex items-center justify-center text-[10px]`} title={`${currentUser.name} (${currentUser.role})`}>
            {currentUser.name.charAt(0)}
          </div>
        </div>
      )}
    </aside>
  );

  return (
    <>
      {/* Desktop & Tablet Persistent Sidebar */}
      <div className="hidden lg:block h-full shrink-0">
        {sidebarContent}
      </div>

      {/* Mobile Drawer Overlay */}
      {isMobileOpen && (
        <div
          id="mobile-sidebar-drawer"
          className="lg:hidden fixed inset-0 z-50 flex"
          role="dialog"
          aria-modal="true"
        >
          {/* Backdrop */}
          <div
            className="fixed inset-0 bg-black/75 backdrop-blur-xs transition-opacity duration-200 animate-fade-in"
            onClick={onCloseMobile}
          />

          {/* Drawer Panel */}
          <div className="relative w-72 max-w-[85vw] h-full shadow-2xl z-10 animate-slide-right">
            {sidebarContent}
          </div>
        </div>
      )}
    </>
  );
};

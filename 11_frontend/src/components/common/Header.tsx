import React, { useState, useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  Menu,
  Bookmark,
  AlertTriangle,
  Layers,
  Search,
  Radio,
  Workflow,
  Activity,
  Shield,
  Bell,
  Sun,
  Moon,
} from 'lucide-react';
import { useUNS } from '../../context/UNSContext';
import { useAlarms } from '../../context/AlarmContext';
import { useTheme } from '../../context/ThemeContext';
import { ConnectionChip } from './ConnectionChip';
import { UserSessionMenu } from './UserSessionMenu';

interface HeaderProps {
  onOpenBookmarks: () => void;
  onOpenStaleDrawer: () => void;
  onToggleMobileSidebar: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  onOpenBookmarks,
  onOpenStaleDrawer,
  onToggleMobileSidebar,
}) => {
  const location = useLocation();
  const navigate = useNavigate();
  const { settings, staleNodesCount, bookmarks } = useUNS();
  const { myUnacknowledgedCount } = useAlarms();
  const { theme, isDark, toggleTheme } = useTheme();

  const [systemTime, setSystemTime] = useState(() => {
    const d = new Date();
    return d.toISOString().replace('T', ' ').slice(0, 19);
  });

  useEffect(() => {
    const timer = setInterval(() => {
      const d = new Date();
      setSystemTime(d.toISOString().replace('T', ' ').slice(0, 19));
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // Compute current section title and icon from route pathname
  const getSectionDetails = () => {
    const path = location.pathname;
    if (path === '/' || path.startsWith('/tree')) {
      return {
        title: 'UNS Tree & Node Hierarchy',
        category: 'ISA-95 Unified Namespace',
        icon: Layers,
      };
    }
    if (path.startsWith('/alerts')) {
      return {
        title: 'Alarm & Alert Management',
        category: 'ISA-18.2 Process Alarms',
        icon: Bell,
      };
    }
    if (path.startsWith('/historian')) {
      return {
        title: 'Historian Explorer & Analytics',
        category: 'TimescaleDB Telemetry',
        icon: Search,
      };
    }
    if (path.startsWith('/sparkplug')) {
      return {
        title: 'Sparkplug B Decoder',
        category: 'Protobuf Edge Nodes',
        icon: Radio,
      };
    }
    if (path.startsWith('/streams')) {
      return {
        title: 'Kafka Event Streaming',
        category: 'Real-time Message Bus',
        icon: Workflow,
      };
    }
    if (path.startsWith('/system')) {
      return {
        title: 'System Health & Operations',
        category: 'Subsystems & Settings',
        icon: Activity,
      };
    }
    if (path.startsWith('/users')) {
      return {
        title: 'User Management & RBAC',
        category: 'Security & Access Matrix',
        icon: Shield,
      };
    }
    return {
      title: 'Console Dashboard',
      category: 'UNS Gateway',
      icon: Layers,
    };
  };

  const section = getSectionDetails();
  const SectionIcon = section.icon;

  return (
    <header className="h-13 border-b border-[#E2E8F0] dark:border-[#1E293B] bg-[#FFFFFF] dark:bg-[#111114] flex items-center justify-between px-3 md:px-4 text-[11px] select-none z-30 shrink-0 shadow-xs transition-colors duration-150">
      {/* Left: Mobile Hamburger Toggle + Breadcrumb */}
      <div className="flex items-center gap-2.5 sm:gap-4 min-w-0">
        {/* Mobile & Tablet Drawer Trigger */}
        <button
          id="mobile-sidebar-toggle-btn"
          onClick={onToggleMobileSidebar}
          className="lg:hidden p-2 -ml-1 rounded-lg bg-[#F1F5F9] dark:bg-[#0B0B0C] border border-[#CBD5E1] dark:border-[#1E293B] hover:border-amber-500 dark:hover:border-[#FFC107] text-[#475569] dark:text-[#94A3B8] hover:text-amber-600 dark:hover:text-[#FFC107] transition-colors cursor-pointer flex items-center justify-center shrink-0"
          title="Open Navigation Menu"
          aria-label="Open Navigation Menu"
        >
          <Menu className="w-4 h-4" />
        </button>

        {/* Section Title / Breadcrumb with Icon */}
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="hidden sm:flex w-7 h-7 rounded-lg bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#E2E8F0] dark:border-[#1E293B] items-center justify-center text-amber-600 dark:text-[#FFC107] shrink-0 shadow-xs">
            <SectionIcon className="w-3.5 h-3.5" />
          </div>

          <div className="min-w-0">
            <div className="flex items-center gap-1.5 text-[10px] text-[#64748B] font-serif tracking-wide leading-none">
              <span className="hidden md:inline font-semibold">UNS Console</span>
              <span className="hidden md:inline text-[#CBD5E1] dark:text-[#334155]">/</span>
              <span className="text-[#475569] dark:text-[#94A3B8] font-medium truncate italic">{section.category}</span>
            </div>
            <h1 className="text-sm sm:text-base font-serif font-bold text-[#0F172A] dark:text-[#F8FAFC] tracking-tight truncate leading-tight mt-0.5">
              {section.title}
            </h1>
          </div>
        </div>
      </div>

      {/* Right: Instance Badge, Bookmarks, Theme Switcher, Stale Warning, Status Chip, User Profile */}
      <div className="flex items-center gap-2 sm:gap-2.5 shrink-0">
        {/* Instance Badge (Compact & No-Wrap) */}
        <div className="hidden md:flex bg-[#F1F5F9] dark:bg-[#0B0B0C] px-2.5 py-1 rounded-md border border-[#E2E8F0] dark:border-[#1E293B] items-center gap-1.5 text-[10px] shrink-0 max-w-[170px]">
          <span className="text-[#64748B] font-mono text-[9px]">INST:</span>
          <span className="font-mono text-[#0F172A] dark:text-[#F8FAFC] font-semibold truncate" title={settings.instance || 'CovestroAG_DRM_01'}>
            {settings.instance || 'CovestroAG_DRM_01'}
          </span>
        </div>

        {/* Alarm Header Quick Badge */}
        {myUnacknowledgedCount > 0 && (
          <button
            id="header-alarm-alert-btn"
            onClick={() => navigate('/alerts')}
            className="flex items-center gap-1.5 px-2 sm:px-2.5 py-1 rounded-md bg-rose-50 dark:bg-rose-500/10 border border-rose-300 dark:border-rose-500/40 text-rose-700 dark:text-rose-300 text-[10px] font-mono hover:bg-rose-100 dark:hover:bg-rose-500/20 transition-colors cursor-pointer shrink-0 animate-pulse font-semibold"
            title={`${myUnacknowledgedCount} unacknowledged alarms targeted to your role`}
          >
            <Bell className="w-3.5 h-3.5 text-rose-600 dark:text-rose-400 shrink-0" />
            <span className="hidden sm:inline font-semibold">{myUnacknowledgedCount} Alarms</span>
            <span className="sm:hidden font-bold">{myUnacknowledgedCount}</span>
          </button>
        )}

        {/* Stale Node Warning Button */}
        {staleNodesCount > 0 && (
          <button
            id="stale-nodes-alert-btn"
            onClick={onOpenStaleDrawer}
            className="flex items-center gap-1.5 px-2 sm:px-2.5 py-1 rounded-md bg-amber-50 dark:bg-amber-500/10 border border-amber-300 dark:border-amber-500/40 text-amber-800 dark:text-[#FFC107] text-[10px] font-mono hover:bg-amber-100 dark:hover:bg-amber-500/20 transition-colors cursor-pointer shrink-0"
            title={`${staleNodesCount} nodes have not received telemetry in > ${settings.staleThresholdMinutes} min`}
          >
            <AlertTriangle className="w-3.5 h-3.5 text-amber-600 dark:text-[#FFC107] animate-pulse shrink-0" />
            <span className="hidden sm:inline font-semibold">{staleNodesCount} Stale</span>
            <span className="sm:hidden font-bold">{staleNodesCount}</span>
          </button>
        )}

        {/* Bookmarks Quick Trigger */}
        <button
          id="bookmarks-toggle-btn"
          onClick={onOpenBookmarks}
          className="flex items-center gap-1.5 px-2 sm:px-2.5 py-1 rounded-md bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#E2E8F0] dark:border-[#1E293B] text-[#475569] dark:text-[#94A3B8] hover:text-amber-600 dark:hover:text-[#FFC107] hover:border-amber-400 dark:hover:border-[#FFC107]/50 text-[10px] font-mono transition-colors cursor-pointer shrink-0"
          title="Saved Topic Bookmarks"
        >
          <Bookmark className="w-3.5 h-3.5 text-amber-600 dark:text-[#FFC107] shrink-0" />
          <span className="hidden xl:inline">Bookmarks</span>
          <span className="px-1.5 py-0.2 rounded bg-[#E2E8F0] dark:bg-[#1E293B] text-[9px] text-amber-700 dark:text-[#FFC107] font-bold border border-[#CBD5E1] dark:border-[#334155]">
            {bookmarks.length}
          </span>
        </button>

        {/* Theme Mode Toggle Button (Light / Dark) */}
        <button
          id="theme-toggle-btn"
          onClick={toggleTheme}
          className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#E2E8F0] dark:border-[#1E293B] text-[#475569] dark:text-[#94A3B8] hover:text-amber-600 dark:hover:text-[#FFC107] hover:border-amber-400 dark:hover:border-[#FFC107]/50 text-[10px] font-mono transition-colors cursor-pointer shrink-0"
          title={`Switch to ${isDark ? 'Light' : 'Dark'} Mode (Default: Light)`}
          aria-label="Toggle Theme Mode"
        >
          {isDark ? (
            <>
              <Sun className="w-3.5 h-3.5 text-[#FFC107]" />
              <span className="hidden xl:inline text-xs font-semibold text-[#FFC107]">Light</span>
            </>
          ) : (
            <>
              <Moon className="w-3.5 h-3.5 text-slate-700" />
              <span className="hidden xl:inline text-xs font-semibold text-slate-700">Dark</span>
            </>
          )}
        </button>

        {/* Live Subsystem Connection Chip */}
        <ConnectionChip />

        {/* User Session Profile & Role Dropdown */}
        <UserSessionMenu />

        {/* Live System Time */}
        <div className="hidden 2xl:block text-right pl-2.5 border-l border-[#E2E8F0] dark:border-[#1E293B] shrink-0">
          <div className="text-[8px] text-[#64748B] uppercase tracking-wider font-mono">System Time</div>
          <div className="font-mono text-[10px] font-bold text-[#0F172A] dark:text-[#F8FAFC]">{systemTime}</div>
        </div>
      </div>
    </header>
  );
};

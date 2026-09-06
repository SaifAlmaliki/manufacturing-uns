import React, { useMemo } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  Menu,
  Bell,
  Calendar,
  Bookmark,
  Sun,
  Moon,
} from 'lucide-react';
import { useUNS } from '../../context/UNSContext';
import { useAlarms } from '../../context/AlarmContext';
import { useAuth } from '../../context/AuthContext';
import { useTheme } from '../../context/ThemeContext';

interface HeaderProps {
  onOpenBookmarks: () => void;
  onOpenStaleDrawer: () => void;
  onToggleMobileSidebar: () => void;
}

function getGreeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return 'Good morning';
  if (hour < 17) return 'Good afternoon';
  return 'Good evening';
}

function getPageHeading(
  path: string,
  firstName: string,
): { title: string; subtitle?: string } {
  if (path.startsWith('/alerts')) {
    return { title: 'Alarm Management' };
  }
  if (path.startsWith('/historian')) {
    return { title: 'Historian' };
  }
  if (path.startsWith('/sparkplug')) {
    return { title: 'Sparkplug B', subtitle: 'Decode Sparkplug B edge node payloads.' };
  }
  if (path.startsWith('/streams')) {
    return { title: 'Kafka Streams', subtitle: 'Watch live Kafka event streams.' };
  }
  if (path.startsWith('/system')) {
    return { title: 'System Health' };
  }
  if (path.startsWith('/users')) {
    return { title: 'Users' };
  }
  if (path.startsWith('/hierarchy')) {
    return { title: 'Plant hierarchy' };
  }
  if (path.startsWith('/connectivity')) {
    return { title: 'Assets & Connectivity' };
  }
  if (path === '/dashboard') {
    return {
      title: `${getGreeting()}, ${firstName} 👋`,
      subtitle: "Here's what's happening across your plant namespace today.",
    };
  }
  if (path.startsWith('/condition-monitoring') || path.startsWith('/tree')) {
    return { title: 'Condition Monitoring' };
  }
  return {
    title: `${getGreeting()}, ${firstName} 👋`,
    subtitle: 'Unified Namespace management console.',
  };
}

export const Header: React.FC<HeaderProps> = ({
  onOpenBookmarks,
  onOpenStaleDrawer,
  onToggleMobileSidebar,
}) => {
  const location = useLocation();
  const navigate = useNavigate();
  const { staleNodesCount, bookmarks } = useUNS();
  const { myUnacknowledgedCount } = useAlarms();
  const { currentUser } = useAuth();
  const { isDark, toggleTheme } = useTheme();

  const todayLabel = useMemo(() => {
    return new Date().toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  }, []);

  const notificationCount = myUnacknowledgedCount + staleNodesCount;

  const handleNotifications = () => {
    if (myUnacknowledgedCount > 0) {
      navigate('/alerts/active');
      return;
    }
    if (staleNodesCount > 0) {
      onOpenStaleDrawer();
    }
  };

  const firstName = currentUser?.name.split(/[\s(]/)[0] ?? 'there';
  const { title, subtitle } = getPageHeading(location.pathname, firstName);

  return (
    <header className="z-30 flex h-14 shrink-0 items-center justify-between border-b border-border bg-background/90 px-4 md:px-6">
      <div className="flex min-w-0 items-center gap-3">
        <button
          id="mobile-sidebar-toggle-btn"
          onClick={onToggleMobileSidebar}
          className="flex size-10 items-center justify-center rounded-md border border-border bg-surface text-muted-foreground transition-colors hover:text-foreground lg:hidden"
          aria-label="Open navigation menu"
        >
          <Menu className="size-5" />
        </button>

        <div className="min-w-0">
          <h1 className="font-heading truncate text-base font-semibold tracking-tight text-foreground md:text-lg">{title}</h1>
          {subtitle && (
            <p className="hidden truncate text-xs text-muted-foreground sm:block">{subtitle}</p>
          )}
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-2 sm:gap-3">
        {/* Date */}
        <button
          className="hidden items-center gap-2 rounded-md border border-border bg-surface px-3 py-2 font-mono text-xs text-foreground transition-colors hover:bg-muted sm:flex"
          aria-label="Current date"
        >
          <Calendar className="size-4 text-muted-foreground" />
          <span className="tabular-nums">{todayLabel}</span>
        </button>

        {/* Bookmarks — subtle icon */}
        <button
          id="bookmarks-toggle-btn"
          onClick={onOpenBookmarks}
          className="relative flex size-10 items-center justify-center rounded-md border border-border bg-surface text-muted-foreground transition-colors hover:text-foreground"
          aria-label={`Bookmarks (${bookmarks.length})`}
          title="Saved bookmarks"
        >
          <Bookmark className="size-[18px]" />
          {bookmarks.length > 0 && (
            <span className="absolute -right-1 -top-1 flex size-4 items-center justify-center rounded-full bg-[#FF7A00] text-[9px] font-bold text-[#140800]">
              {bookmarks.length > 9 ? '9+' : bookmarks.length}
            </span>
          )}
        </button>

        {/* Theme toggle */}
        <button
          id="theme-toggle-btn"
          onClick={toggleTheme}
          className="flex size-10 items-center justify-center rounded-md border border-border bg-surface text-muted-foreground transition-colors hover:text-foreground"
          aria-label={`Switch to ${isDark ? 'light' : 'dark'} mode`}
        >
          {isDark ? <Sun className="size-[18px]" /> : <Moon className="size-[18px]" />}
        </button>

        {/* Notifications */}
        <button
          id="header-notifications-btn"
          onClick={handleNotifications}
          className="relative flex size-10 items-center justify-center rounded-md border border-border bg-surface text-muted-foreground transition-colors hover:text-foreground"
          aria-label={`Notifications (${notificationCount})`}
          title={
            notificationCount > 0
              ? `${myUnacknowledgedCount} alarms, ${staleNodesCount} stale nodes`
              : 'No notifications'
          }
        >
          <Bell className="size-[18px]" />
          {notificationCount > 0 && (
            <span className="absolute -right-1 -top-1 flex size-[18px] items-center justify-center rounded-full bg-red-500 text-[10px] font-semibold text-white tabular-nums">
              {notificationCount > 9 ? '9+' : notificationCount}
            </span>
          )}
        </button>
      </div>
    </header>
  );
};

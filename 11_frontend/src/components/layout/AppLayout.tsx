import React, { useState, useEffect } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { Header } from '../common/Header';
import { BookmarksDrawer } from '../system/BookmarksDrawer';
import { StaleNodesDrawer } from '../system/StaleNodesDrawer';
import { useUNS } from '../../context/UNSContext';
import { useAuth } from '../../context/AuthContext';
import { AccessRestricted } from '../common/AccessRestricted';

export const AppLayout: React.FC = () => {
  const location = useLocation();
  const { health, allLoadedNodes, staleNodesCount, setActiveTab } = useUNS();
  const { canAccessTab } = useAuth();

  const [isCollapsed, setIsCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem('uns_sidebar_collapsed') === 'true';
    } catch {
      return false;
    }
  });

  const [isMobileOpen, setIsMobileOpen] = useState(false);
  const [isBookmarksOpen, setIsBookmarksOpen] = useState(false);
  const [isStaleDrawerOpen, setIsStaleDrawerOpen] = useState(false);

  const getTabIdFromPath = (path: string): string => {
    if (path === '/dashboard' || path === '/tree') return 'home';
    if (path.startsWith('/alerts')) return 'alarms';
    if (path.startsWith('/historian')) return 'explore';
    if (path.startsWith('/sparkplug')) return 'sparkplug';
    if (path.startsWith('/streams')) return 'streams';
    if (path.startsWith('/system')) return 'system';
    if (path.startsWith('/simulator')) return 'simulator';
    if (path.startsWith('/users')) return 'users';
    if (path.startsWith('/hierarchy')) return 'hierarchy';
    if (path.startsWith('/connectivity')) return 'connectivity';
    return 'home';
  };

  const currentTabId = getTabIdFromPath(location.pathname);
  const tabAccess = canAccessTab(currentTabId);

  useEffect(() => {
    setActiveTab(currentTabId as Parameters<typeof setActiveTab>[0]);
  }, [currentTabId, setActiveTab]);

  const handleToggleCollapse = () => {
    setIsCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem('uns_sidebar_collapsed', String(next));
      } catch {
        // ignore
      }
      return next;
    });
  };

  const connectionLabel =
    health.status === 'LIVE' ? 'Connected' : health.status === 'DEGRADED' ? 'Degraded' : 'Offline';

  return (
    <div className="console-shell flex h-dvh w-screen overflow-hidden bg-background font-sans text-foreground">
      <Sidebar
        isCollapsed={isCollapsed}
        onToggleCollapse={handleToggleCollapse}
        isMobileOpen={isMobileOpen}
        onCloseMobile={() => setIsMobileOpen(false)}
      />

      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <Header
          onOpenBookmarks={() => setIsBookmarksOpen(true)}
          onOpenStaleDrawer={() => setIsStaleDrawerOpen(true)}
          onToggleMobileSidebar={() => setIsMobileOpen((prev) => !prev)}
        />

        <main className="flex min-h-0 flex-1 overflow-hidden bg-transparent">
          {!tabAccess.allowed ? (
            <AccessRestricted
              featureKey={tabAccess.requiredFeature}
              featureName={tabAccess.featureName}
              onNavigateHome={() => {
                window.location.hash = '#/dashboard';
              }}
            />
          ) : (
            <Outlet />
          )}
        </main>

        <footer className="flex h-8 shrink-0 items-center justify-between border-t border-border bg-surface px-4 font-mono text-[11px] text-muted-foreground">
          <div className="flex items-center gap-3">
            <span
              className={`flex items-center gap-1.5 font-medium ${
                health.status === 'LIVE'
                  ? 'text-emerald-500'
                  : health.status === 'DEGRADED'
                    ? 'text-amber-500'
                    : 'text-red-500'
              }`}
            >
              <span
                className={`size-1.5 rounded-full ${
                  health.status === 'LIVE'
                    ? 'bg-emerald-500'
                    : health.status === 'DEGRADED'
                      ? 'bg-amber-500'
                      : 'bg-red-500'
                }`}
              />
              {connectionLabel}
            </span>
            <span className="hidden text-muted-foreground/70 sm:inline">·</span>
            <span className="hidden tabular-nums sm:inline">
              {allLoadedNodes.length} nodes
            </span>
          </div>

          <div className="flex items-center gap-3 tabular-nums">
            {staleNodesCount > 0 && (
              <span className="font-medium text-amber-500">{staleNodesCount} stale</span>
            )}
            <span className="hidden text-muted-foreground md:inline">Mode: {health.mode}</span>
          </div>
        </footer>
      </div>

      <BookmarksDrawer isOpen={isBookmarksOpen} onClose={() => setIsBookmarksOpen(false)} />
      <StaleNodesDrawer isOpen={isStaleDrawerOpen} onClose={() => setIsStaleDrawerOpen(false)} />
    </div>
  );
};

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

  // Desktop sidebar collapse preference (stored in localStorage)
  const [isCollapsed, setIsCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem('uns_sidebar_collapsed') === 'true';
    } catch {
      return false;
    }
  });

  // Mobile/Tablet drawer state
  const [isMobileOpen, setIsMobileOpen] = useState(false);

  // Drawers
  const [isBookmarksOpen, setIsBookmarksOpen] = useState(false);
  const [isStaleDrawerOpen, setIsStaleDrawerOpen] = useState(false);

  // Map route to tab ID for RBAC checks
  const getTabIdFromPath = (path: string): string => {
    if (path === '/' || path.startsWith('/tree')) return 'home';
    if (path.startsWith('/alerts')) return 'alarms';
    if (path.startsWith('/historian')) return 'explore';
    if (path.startsWith('/sparkplug')) return 'sparkplug';
    if (path.startsWith('/streams')) return 'streams';
    if (path.startsWith('/system')) return 'system';
    if (path.startsWith('/simulator')) return 'simulator';
    if (path.startsWith('/users')) return 'users';
    return 'home';
  };

  const currentTabId = getTabIdFromPath(location.pathname);
  const tabAccess = canAccessTab(currentTabId);

  // Keep activeTab in sync with route
  useEffect(() => {
    setActiveTab(currentTabId as any);
  }, [currentTabId, setActiveTab]);

  // Handle toggle desktop collapse
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

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[#F8FAFC] dark:bg-[#050505] text-[#0F172A] dark:text-[#E2E8F0] font-sans select-none text-[11px] transition-colors duration-150">
      {/* Left Application Sidebar / Left Menu */}
      <Sidebar
        isCollapsed={isCollapsed}
        onToggleCollapse={handleToggleCollapse}
        isMobileOpen={isMobileOpen}
        onCloseMobile={() => setIsMobileOpen(false)}
        onOpenBookmarks={() => setIsBookmarksOpen(true)}
        onOpenStaleDrawer={() => setIsStaleDrawerOpen(true)}
      />

      {/* Main Content Pane */}
      <div className="flex-1 flex flex-col h-full min-w-0 overflow-hidden bg-[#F8FAFC] dark:bg-[#050505]">
        {/* Responsive Header Bar */}
        <Header
          onOpenBookmarks={() => setIsBookmarksOpen(true)}
          onOpenStaleDrawer={() => setIsStaleDrawerOpen(true)}
          onToggleMobileSidebar={() => setIsMobileOpen((prev) => !prev)}
        />

        {/* Dynamic Route View Content with Zero-Trust RBAC Guard */}
        <main className="flex-1 flex overflow-hidden min-h-0 bg-[#F8FAFC] dark:bg-[#050505]">
          {!tabAccess.allowed ? (
            <AccessRestricted
              featureKey={tabAccess.requiredFeature}
              featureName={tabAccess.featureName}
              onNavigateHome={() => {
                window.location.hash = '#/tree';
              }}
            />
          ) : (
            <Outlet />
          )}
        </main>

        {/* Industrial High Density Status Footer */}
        <footer className="h-6 bg-[#FFFFFF] dark:bg-[#111114] border-t border-[#E2E8F0] dark:border-[#1E293B] px-3 md:px-4 flex items-center justify-between text-[9px] uppercase tracking-wider text-[#64748B] font-mono shrink-0 select-none shadow-sm">
          <div className="flex items-center gap-3 sm:gap-4">
            <span className="text-[#334155] dark:text-[#94A3B8] font-medium">GQL: 8000</span>
            <span className="hidden sm:inline text-[#64748B]">VITE: 3000</span>
            <span className="hidden md:inline text-[#64748B]">SCHEMA: 2026.08.28-v2</span>
            <span className="text-emerald-600 dark:text-emerald-400 font-bold">MODE: {health.mode}</span>
          </div>

          <div className="flex items-center gap-3 sm:gap-4">
            <span className="flex items-center gap-1.5 text-emerald-600 dark:text-[#10B981] font-semibold">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 dark:bg-[#10B981] animate-pulse" />
              <span className="hidden sm:inline">Connected to UNS Backend</span>
              <span className="sm:hidden">Connected</span>
            </span>
            <span className="text-[#334155] dark:text-[#94A3B8] font-medium">Nodes: {allLoadedNodes.length || 28}</span>
            {staleNodesCount > 0 && (
              <span className="text-amber-600 dark:text-[#FFC107] font-bold">Stale: {staleNodesCount}</span>
            )}
          </div>
        </footer>
      </div>

      {/* Global Slide-Over Drawers */}
      <BookmarksDrawer
        isOpen={isBookmarksOpen}
        onClose={() => setIsBookmarksOpen(false)}
      />
      <StaleNodesDrawer
        isOpen={isStaleDrawerOpen}
        onClose={() => setIsStaleDrawerOpen(false)}
      />
    </div>
  );
};

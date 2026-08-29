/**
 * Unified Namespace (UNS) Console Main Application Component
 * Communicates exclusively with 07_uns_graphql via HTTP & WS /graphql
 * Modern Multi-Route Architecture:
 * - Public Landing Page (/) with generated industrial hero image & feature highlights
 * - Public Login Portal (/login) with 1-click RBAC role switching & enterprise auth
 * - Protected Console Platform (/tree, /alerts, /historian, etc.)
 */

import React from 'react';
import { HashRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { ThemeProvider } from './context/ThemeContext';
import { UNSProvider } from './context/UNSContext';
import { AuthProvider, useAuth } from './context/AuthContext';
import { AlarmProvider } from './context/AlarmContext';
import { AppLayout } from './components/layout/AppLayout';
import { LandingView } from './components/landing/LandingView';
import { LoginView } from './components/auth/LoginView';
import { HomeView } from './components/home/HomeView';
import { ExploreView } from './components/explore/ExploreView';
import { SparkplugView } from './components/sparkplug/SparkplugView';
import { KafkaStreamsView } from './components/streams/KafkaStreamsView';
import { AlarmManagementView } from './components/alarms/AlarmManagementView';
import { SystemHealthView } from './components/system/SystemHealthView';
import { UserManagementView } from './components/users/UserManagementView';

/**
 * Zero-Trust Protected Console Layout Guard
 * If user has not authenticated, routes to the Enterprise Login Portal.
 */
const ProtectedConsoleLayout: React.FC = () => {
  const { isAuthenticated } = useAuth();
  const location = useLocation();

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return <AppLayout />;
};

export default function App() {
  return (
    <ThemeProvider>
      <HashRouter>
        <AuthProvider>
          <UNSProvider>
            <AlarmProvider>
              <Routes>
                {/* 1. Public Landing Page */}
                <Route path="/" element={<LandingView />} />

                {/* 2. Public Login Portal */}
                <Route path="/login" element={<LoginView />} />

                {/* 3. Protected Enterprise Console Platform */}
                <Route element={<ProtectedConsoleLayout />}>
                  <Route path="/tree" element={<HomeView />} />
                  <Route path="/alerts" element={<AlarmManagementView />} />
                  <Route path="/historian" element={<ExploreView />} />
                  <Route path="/sparkplug" element={<SparkplugView />} />
                  <Route path="/streams" element={<KafkaStreamsView />} />
                  <Route path="/system" element={<SystemHealthView />} />
                  <Route path="/users" element={<UserManagementView />} />
                </Route>

                {/* Catch-all Wildcard: return to landing page */}
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </AlarmProvider>
          </UNSProvider>
        </AuthProvider>
      </HashRouter>
    </ThemeProvider>
  );
}

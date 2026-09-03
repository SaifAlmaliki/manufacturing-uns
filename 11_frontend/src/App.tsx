/**
 * Unified Namespace (UNS) Console Main Application Component
 * Communicates with 07_uns_graphql for all platform data, and — only on the /simulator
 * route — directly with 99_simulator's control API. See docs/adr/0007.
 * Modern Multi-Route Architecture:
 * - Public Landing Page (/) with generated industrial hero image & feature highlights
 * - Public Login Portal (/login) — one button that redirects to the Keycloak realm
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
import { DashboardView } from './components/dashboard/DashboardView';
import { ExploreView } from './components/explore/ExploreView';
import { SparkplugView } from './components/sparkplug/SparkplugView';
import { KafkaStreamsView } from './components/streams/KafkaStreamsView';
import { AlarmManagementLayout } from './components/alarms/AlarmManagementLayout';
import { AlarmActiveTab } from './components/alarms/AlarmActiveTab';
import { AlarmRulesTab } from './components/alarms/AlarmRulesTab';
import { RoleAlertMatrix } from './components/alarms/RoleAlertMatrix';
import { AlarmAuditLog } from './components/alarms/AlarmAuditLog';
import { SystemHealthView } from './components/system/SystemHealthView';
import { SimulatorView } from './components/simulator/SimulatorView';
import { UserManagementView } from './components/users/UserManagementView';

/**
 * Zero-Trust Protected Console Layout Guard
 * If user has not authenticated, routes to the Enterprise Login Portal.
 */
const ProtectedConsoleLayout: React.FC = () => {
  const { isAuthenticated, isReady } = useAuth();
  const location = useLocation();

  // Until the first sign-in check settles, identity is unknown: a refresh on a deep link
  // would otherwise bounce a signed-in user to the landing page before the silent renew
  // against the realm has finished.
  if (!isReady) {
    return null;
  }

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
                  <Route path="/dashboard" element={<DashboardView />} />
                  <Route path="/tree" element={<HomeView />} />
                  <Route path="/alerts" element={<AlarmManagementLayout />}>
                    <Route index element={<Navigate to="active" replace />} />
                    <Route path="active" element={<AlarmActiveTab />} />
                    <Route path="rules" element={<AlarmRulesTab />} />
                    <Route path="matrix" element={<RoleAlertMatrix />} />
                    <Route path="audit" element={<AlarmAuditLog />} />
                  </Route>
                  <Route path="/historian" element={<ExploreView />} />
                  <Route path="/sparkplug" element={<SparkplugView />} />
                  <Route path="/streams" element={<KafkaStreamsView />} />
                  <Route path="/system" element={<SystemHealthView />} />
                  {/* HashRouter, so this is #/simulator — the HTTP path stays / and does
                      not collide with the /simulator proxy that reaches the control API. */}
                  <Route path="/simulator" element={<SimulatorView />} />
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

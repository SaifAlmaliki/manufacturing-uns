/**
 * Who is signed in, according to the realm.
 *
 * The provider keeps the shape its consumers already use so that a dozen components do not
 * change at once. What changed is everything behind it: there is no user directory in this
 * file, no permission matrix in localStorage, and no login that accepts any password.
 *
 * `hasPermission` gates UI affordances only. What the server accepts is decided by
 * 07_uns_graphql/src/uns_graphql/auth/require.py, and a control this file enables is still
 * refused there if the role is wrong.
 */

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

import { authClient } from '../lib/auth/oidc';
import type { Session } from '../lib/auth/oidc';
import { featureAllowed } from '../lib/auth/roles';
import { FeatureKey, ROLE_CONFIGS, UserAccount, UserRole } from '../types/rbac';

interface AuthContextType {
  session: Session | null;
  currentUser: UserAccount | null;
  isAuthenticated: boolean;
  isAdmin: boolean;
  /** False until the first sign-in check settles. Nothing should route on identity before it. */
  isReady: boolean;
  roles: UserRole[];
  login: () => void;
  logout: () => void;
  hasPermission: (feature: FeatureKey) => boolean;
  canAccessTab: (tab: string) => { allowed: boolean; requiredFeature: FeatureKey; featureName: string };
}

const AuthContext = createContext<AuthContextType | null>(null);

// The tab gating table. If the surfaces plan renames a route key, this table's keys change
// with it; a stale key here silently falls back to `home` and gates the wrong screen.
const TAB_FEATURES: Record<string, { feature: FeatureKey; name: string }> = {
  home: { feature: 'uns_tree', name: 'Plant' },
  explore: { feature: 'historian', name: 'Historian' },
  sparkplug: { feature: 'sparkplug', name: 'Sparkplug' },
  alarms: { feature: 'alarms', name: 'Alarms' },
  system: { feature: 'system_ops', name: 'Health' },
  users: { feature: 'user_management', name: 'Users' },
  hierarchy: { feature: 'settings_edit', name: 'Plant hierarchy' },
  connectivity: { feature: 'connectivity', name: 'Assets & Connectivity' },
};

/**
 * The realm's view of a person, in the shape the existing chrome renders.
 *
 * `department` and `plantLocation` are required by `UserAccount` and empty here, because the
 * realm does not hold them. Inventing 'Process Engineering' and 'Dormagen' is exactly what the
 * five seeded accounts did. `avatarColor` is deliberately omitted: it is optional on
 * `UserAccount` and both consumers already fall back to `bg-[#FFC107]`.
 *
 * `session.roles[0]` is a lossy narrowing: a realm user can hold several roles. Because
 * CONSOLE_ROLES is ordered most-privileged first and rolesFromClaims preserves that order,
 * roles[0] is the *highest* role held, so the badge never under-reports. It is only ever a
 * display value: `hasPermission` reads the whole `roles` array. Nothing may gate on
 * `currentUser.role`; use `isAdmin` or `hasPermission(...)`.
 */
function toAccount(session: Session): UserAccount {
  const role = session.roles[0] ?? 'viewer';
  return {
    id: session.subject,
    name: session.displayName,
    email: session.email ?? session.username,
    role,
    department: '',
    plantLocation: '',
    status: 'active',
    createdAt: '',
    lastLogin: '',
    // The role's profile, with no per-user overrides: the realm is the only authority on what
    // somebody may do, and a customPermissions map in the browser was a permission matrix
    // the server never saw.
    customPermissions: { ...ROLE_CONFIGS[role].defaultPermissions },
  };
}

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [session, setSession] = useState<Session | null>(null);
  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    let cancelled = false;

    const start = async () => {
      // Order matters: a redirect back from the realm carries a one-time code, and racing a
      // silent renew against it can discard the session just granted.
      try {
        const fromRedirect = await authClient.completeRedirect();
        const resolved = fromRedirect ?? (await authClient.restore());
        if (!cancelled) {
          setSession(resolved);
        }
      } catch {
        // A failed callback must not leave isReady false: the public landing page would
        // otherwise sit behind a blank screen, and the unhandled rejection restarts nothing.
      } finally {
        if (!cancelled) {
          setIsReady(true);
        }
      }
    };

    void start();
    const stop = authClient.onSession((next) => {
      if (!cancelled) {
        setSession(next);
      }
    });

    return () => {
      cancelled = true;
      stop();
    };
  }, []);

  const roles = useMemo(() => session?.roles ?? [], [session]);
  const currentUser = useMemo(() => (session ? toAccount(session) : null), [session]);

  const hasPermission = useCallback(
    (feature: FeatureKey) => featureAllowed(roles, feature),
    [roles],
  );

  const canAccessTab = useCallback(
    (tab: string) => {
      const required = TAB_FEATURES[tab] ?? TAB_FEATURES.home;
      return {
        allowed: hasPermission(required.feature),
        requiredFeature: required.feature,
        featureName: required.name,
      };
    },
    [hasPermission],
  );

  const value = useMemo<AuthContextType>(
    () => ({
      session,
      currentUser,
      isAuthenticated: session !== null,
      isAdmin: roles.includes('admin'),
      isReady,
      roles,
      login: () => { void authClient.signIn(); },
      logout: () => { void authClient.signOut(); },
      hasPermission,
      canAccessTab,
    }),
    [session, currentUser, roles, isReady, hasPermission, canAccessTab],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return ctx;
};

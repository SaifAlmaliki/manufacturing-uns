/**
 * The console's side of Authorization Code + PKCE.
 *
 * No React here on purpose: this is testable without rendering, and AuthContext
 * becomes a thin wrapper whose own tests can stub it.
 *
 * Where things are kept, and why:
 * - The access token is in a module-local variable. It is never in localStorage or
 *   sessionStorage; persisting identity in localStorage is what made the previous design
 *   fake, and a token there is readable by any script on the origin.
 * - The PKCE `code_verifier` and the `state` do go in sessionStorage, because they must
 *   survive a full-page navigation to the realm and back. They are single-use and worthless
 *   without the matching authorization code.
 * - A page refresh therefore has no token. `restore()` gets one back through a hidden-iframe
 *   silent renew, which works because the realm is served from the console's own origin,
 *   making Keycloak's SSO cookie a first-party cookie.
 */

import {
  InMemoryWebStorage,
  User,
  UserManager,
  WebStorageStateStore,
} from 'oidc-client-ts';

import { platformConfig } from '../platform/config';
import { rolesFromClaims } from './roles';
import type { UserRole } from '../../types/rbac';

export interface Session {
  subject: string;
  username: string;
  email?: string;
  displayName: string;
  roles: UserRole[];
}

export interface AuthClient {
  completeRedirect(): Promise<Session | null>;
  restore(): Promise<Session | null>;
  signIn(): Promise<void>;
  signOut(): Promise<void>;
  accessToken(): string | null;
  refresh(): Promise<string | null>;
  onSession(listener: (session: Session | null) => void): () => void;
}

export interface AuthSettings {
  /** Injected by the tests. Production passes nothing and gets a real UserManager. */
  manager: UserManager;
}

function buildManager(): UserManager {
  return new UserManager({
    authority: platformConfig.authIssuer,
    client_id: platformConfig.authClientId,
    // The realm lists http://localhost:8088/* and :5173/*, so the origin is enough. A path
    // would have to be kept in step with the realm export in two repositories' worth of
    // places.
    redirect_uri: `${window.location.origin}/`,
    post_logout_redirect_uri: `${window.location.origin}/`,
    response_type: 'code',
    scope: 'openid profile email',
    // In memory, not sessionStorage: see the module comment.
    userStore: new WebStorageStateStore({ store: new InMemoryWebStorage() }),
    // The code_verifier, which must survive the navigation. Not a token.
    stateStore: new WebStorageStateStore({ store: window.sessionStorage }),
    automaticSilentRenew: true,
    // The console shows plant data that moves; an expiring token mid-shift must not surface
    // as an empty table.
    accessTokenExpiringNotificationTimeInSeconds: 60,
    monitorSession: false,
  });
}

function payloadFromJwt(token: string): Record<string, unknown> | null {
  const parts = token.split('.');
  if (parts.length < 2) {
    return null;
  }
  try {
    const padded = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    const pad = padded.length % 4 === 0 ? '' : '='.repeat(4 - (padded.length % 4));
    const parsed: unknown = JSON.parse(atob(padded + pad));
    return parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

function toSession(user: User | null | undefined): Session | null {
  if (!user?.access_token) {
    return null;
  }
  const profile = user.profile as Record<string, unknown>;
  const accessClaims = payloadFromJwt(user.access_token);
  const username = String(profile.preferred_username ?? profile.sub ?? '');
  const fromAccess = rolesFromClaims(accessClaims);
  return {
    subject: String(profile.sub ?? ''),
    username,
    email: typeof profile.email === 'string' ? profile.email : undefined,
    // What the header shows. Falls back to the username rather than to an empty chip.
    displayName: typeof profile.name === 'string' && profile.name ? profile.name : username,
    // Keycloak's default roles mapper puts realm_access on the access token, not the ID
    // token that oidc-client-ts exposes as user.profile.
    roles: fromAccess.length > 0 ? fromAccess : rolesFromClaims(profile),
  };
}

function isRedirectCallback(): boolean {
  const params = new URLSearchParams(window.location.search);
  // Both, not either: `state` alone is an ordinary query parameter somebody might use, and
  // calling signinCallback outside a real callback throws.
  return params.has('code') && params.has('state');
}

export function createAuthClient(overrides?: Partial<AuthSettings>): AuthClient {
  const manager = overrides?.manager ?? buildManager();
  let token: string | null = null;
  const listeners = new Set<(session: Session | null) => void>();

  const publish = (session: Session | null) => {
    listeners.forEach((listener) => listener(session));
  };

  const adopt = (user: User | null | undefined): Session | null => {
    const session = toSession(user);
    token = session ? (user as User).access_token : null;
    return session;
  };

  // A renew that happens on its own timer still has to update the token this module hands out.
  manager.events?.addUserLoaded?.((user: User) => {
    const session = adopt(user);
    if (session) {
      publish(session);
    }
  });

  return {
    async completeRedirect() {
      if (!isRedirectCallback()) {
        return null;
      }
      try {
        const user = await manager.signinCallback();
        const session = adopt(user as User | null);
        if (session) {
          publish(session);
        }
        return session;
      } catch {
        // A missing PKCE verifier, a reused code, or a raced second callback. Swallowing
        // lets restore() try a silent renew, and the landing page stays reachable.
        return null;
      } finally {
        // An authorization code left in the address bar gets pasted into chat messages and
        // saved into bookmarks. The hash is the app's route and stays.
        window.history.replaceState({}, '', `${window.location.pathname}${window.location.hash}`);
      }
    },

    async restore() {
      try {
        const user = await manager.signinSilent();
        const session = adopt(user as User | null);
        if (session) {
          publish(session);
        }
        return session;
      } catch {
        // No realm session. Not an error: this is what an anonymous visitor looks like, and
        // redirecting from here would make the landing page unreachable.
        return null;
      }
    },

    async signIn() {
      await manager.signinRedirect();
    },

    async signOut() {
      token = null;
      publish(null);
      await manager.removeUser();
      await manager.signoutRedirect();
    },

    accessToken() {
      return token;
    },

    async refresh() {
      try {
        const user = await manager.signinSilent();
        const session = adopt(user as User | null);
        if (session) {
          publish(session);
        }
        return token;
      } catch {
        return null;
      }
    },

    onSession(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

/** The app's one client. The GraphQL client reads its token from here. */
export const authClient: AuthClient = createAuthClient();

/**
 * Realm roles to console roles.
 *
 * The realm is the authority on who holds what. This module only translates, and drops what
 * it does not recognise — Keycloak issues `offline_access`, `uma_authorization` and
 * `default-roles-<realm>` to every user, and none of them mean anything here.
 */

import { FeatureKey, ROLE_CONFIGS, UserRole } from '../../types/rbac';

export const CONSOLE_ROLES: readonly UserRole[] = [
  'admin',
  'engineer',
  'operator',
  'auditor',
  'viewer',
];

const KNOWN = new Set<string>(CONSOLE_ROLES);

/**
 * The console's role names are lower case, the GraphQL enum members are not.
 * Anything unrecognised is dropped rather than guessed.
 */
export function toUserRole(role: string | null | undefined): UserRole | undefined {
  const candidate = String(role ?? '').toLowerCase();
  return KNOWN.has(candidate) ? (candidate as UserRole) : undefined;
}

/** The realm roles in an access token, filtered to the five and ordered as CONSOLE_ROLES is. */
export function rolesFromClaims(claims: unknown): UserRole[] {
  const realmAccess = (claims as { realm_access?: unknown } | null)?.realm_access;
  const granted = (realmAccess as { roles?: unknown } | undefined)?.roles;
  if (!Array.isArray(granted)) {
    // A misshapen token is not a crash. This runs before the first render.
    return [];
  }
  const held = new Set(granted.map(toUserRole).filter((r): r is UserRole => r !== undefined));
  // Ordered by CONSOLE_ROLES so that two tokens with the same roles produce the same array,
  // which is what lets React skip a re-render and a test assert without sorting.
  return CONSOLE_ROLES.filter((role) => held.has(role));
}

/**
 * Whether any held role's profile grants this feature.
 *
 * The profiles are `ROLE_CONFIGS[role].defaultPermissions`, which already exists and is
 * already what the UI was built around. A second table would be a second thing to keep in
 * step. Note what this is not: it decides which controls the console offers, and
 * `07_uns_graphql/src/uns_graphql/auth/require.py` decides what the server accepts.
 */
export function featureAllowed(roles: UserRole[], feature: FeatureKey): boolean {
  return roles.some((role) => ROLE_CONFIGS[role]?.defaultPermissions?.[feature] === true);
}

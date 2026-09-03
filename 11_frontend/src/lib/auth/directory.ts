/**
 * The realm's membership, read with the signed-in admin's own token.
 *
 * There is no user directory in this console. Keycloak has one, and this reads it.
 * The realm may refuse — reading /admin/realms/{realm}/users needs realm-management's
 * view-users role, which conf/keycloak/realm.json grants to `admin` as a composite.
 */

import { platformConfig } from '../platform/config';
import { authClient } from './oidc';
import { toUserRole } from './roles';
import type { UserRole } from '../../types/rbac';

export interface RealmMember {
  id: string;
  username: string;
  email?: string;
  displayName: string;
  enabled: boolean;
  roles: UserRole[];
}

export type DirectoryResult =
  | { kind: 'members'; members: RealmMember[] }
  | { kind: 'forbidden' }
  | { kind: 'unreachable'; detail: string };

/** Keycloak's admin base, e.g. http://localhost:8088/auth/admin/realms/uns */
function adminBase(): string {
  return `${platformConfig.authBaseUrl}/admin/realms/${platformConfig.authRealm}`;
}

function authHeaders(): Record<string, string> {
  const token = authClient.accessToken();
  return token ? { Authorization: `Bearer ${token}`, Accept: 'application/json' } : { Accept: 'application/json' };
}

interface KeycloakUser {
  id: string;
  username: string;
  email?: string;
  firstName?: string;
  lastName?: string;
  enabled?: boolean;
}

function displayName(user: KeycloakUser): string {
  const full = [user.firstName, user.lastName].filter(Boolean).join(' ').trim();
  return full || user.username;
}

async function rolesOf(
  fetchImpl: typeof fetch,
  userId: string,
): Promise<UserRole[]> {
  try {
    const response = await fetchImpl(`${adminBase()}/users/${userId}/role-mappings/realm`, {
      headers: authHeaders(),
    });
    if (!response.ok) {
      return [];
    }
    const granted = (await response.json()) as { name?: string }[];
    return granted
      .map((role) => toUserRole(role.name))
      .filter((role): role is UserRole => role !== undefined);
  } catch {
    return [];
  }
}

export async function fetchRealmMembers(fetchImpl: typeof fetch = fetch): Promise<DirectoryResult> {
  try {
    const response = await fetchImpl(
      `${adminBase()}/users?briefRepresentation=false&max=500`,
      { headers: authHeaders() },
    );

    if (response.status === 401 || response.status === 403) {
      return { kind: 'forbidden' };
    }
    if (!response.ok) {
      return { kind: 'unreachable', detail: `The realm answered ${response.status}.` };
    }

    const users = (await response.json()) as KeycloakUser[];
    const members = await Promise.all(
      users.map(async (user) => ({
        id: user.id,
        username: user.username,
        email: user.email,
        displayName: displayName(user),
        enabled: user.enabled !== false,
        roles: await rolesOf(fetchImpl, user.id),
      })),
    );
    return { kind: 'members', members };
  } catch (error) {
    return { kind: 'unreachable', detail: error instanceof Error ? error.message : String(error) };
  }
}

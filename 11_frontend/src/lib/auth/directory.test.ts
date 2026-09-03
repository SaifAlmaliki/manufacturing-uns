import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchRealmMembers } from './directory';

vi.mock('./oidc', () => ({
  authClient: { accessToken: () => 'admin.access.token' },
}));

const KEYCLOAK_USERS = [
  {
    id: 'kc-1',
    username: 'engineer.user',
    email: 'engineer.user@example.test',
    firstName: 'Erin',
    lastName: 'Engineer',
    enabled: true,
  },
  { id: 'kc-2', username: 'service-account-thing', enabled: true },
];

const json = (status: number, body: unknown) =>
  ({ ok: status < 400, status, json: async () => body }) as unknown as Response;

beforeEach(() => vi.clearAllMocks());

describe('fetchRealmMembers', () => {
  it('asks the realm, with the signed-in user token', async () => {
    const f = vi.fn()
      .mockResolvedValueOnce(json(200, KEYCLOAK_USERS))
      .mockResolvedValue(json(200, [{ name: 'engineer' }]));

    await fetchRealmMembers(f as unknown as typeof fetch);

    const [url, init] = f.mock.calls[0];
    expect(String(url)).toContain('/admin/realms/uns/users');
    expect((init.headers as Record<string, string>).Authorization)
      .toBe('Bearer admin.access.token');
  });

  it('reads each member’s realm roles and drops the ones Keycloak gives everybody', async () => {
    const f = vi.fn().mockImplementation(async (url: string) =>
      String(url).includes('/role-mappings/realm')
        ? json(200, [{ name: 'engineer' }, { name: 'default-roles-uns' }])
        : json(200, [KEYCLOAK_USERS[0]]),
    );

    const result = await fetchRealmMembers(f as unknown as typeof fetch);

    expect(result).toEqual({
      kind: 'members',
      members: [{
        id: 'kc-1',
        username: 'engineer.user',
        email: 'engineer.user@example.test',
        displayName: 'Erin Engineer',
        enabled: true,
        roles: ['engineer'],
      }],
    });
  });

  it('falls back to the username when the realm holds no name', async () => {
    const f = vi.fn().mockImplementation(async (url: string) =>
      String(url).includes('/role-mappings/realm') ? json(200, []) : json(200, [KEYCLOAK_USERS[1]]),
    );

    const result = await fetchRealmMembers(f as unknown as typeof fetch);

    expect(result).toMatchObject({
      members: [{ displayName: 'service-account-thing', roles: [] }],
    });
  });

  it('reports forbidden rather than empty when the realm refuses the token', async () => {
    const f = vi.fn().mockResolvedValue(json(403, {}));

    expect(await fetchRealmMembers(f as unknown as typeof fetch)).toEqual({ kind: 'forbidden' });
  });

  it('reports forbidden on a 401 too', async () => {
    const f = vi.fn().mockResolvedValue(json(401, {}));

    expect(await fetchRealmMembers(f as unknown as typeof fetch)).toEqual({ kind: 'forbidden' });
  });

  it('reports unreachable when the realm is not there at all', async () => {
    const f = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));

    const result = await fetchRealmMembers(f as unknown as typeof fetch);

    expect(result).toMatchObject({ kind: 'unreachable' });
    expect((result as { detail: string }).detail).toContain('Failed to fetch');
  });

  it('still lists a member whose role lookup fails, with no roles', async () => {
    const f = vi.fn().mockImplementation(async (url: string) =>
      String(url).includes('/role-mappings/realm') ? json(500, {}) : json(200, [KEYCLOAK_USERS[0]]),
    );

    const result = await fetchRealmMembers(f as unknown as typeof fetch);

    expect(result).toMatchObject({ members: [{ username: 'engineer.user', roles: [] }] });
  });
});

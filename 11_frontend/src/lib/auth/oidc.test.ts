import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createAuthClient } from './oidc';

/** A minimal stand-in for oidc-client-ts's UserManager. */
function fakeManager(overrides: Record<string, unknown> = {}) {
  return {
    signinRedirect: vi.fn().mockResolvedValue(undefined),
    signinCallback: vi.fn().mockResolvedValue(null),
    signinSilent: vi.fn().mockResolvedValue(null),
    signoutRedirect: vi.fn().mockResolvedValue(undefined),
    getUser: vi.fn().mockResolvedValue(null),
    removeUser: vi.fn().mockResolvedValue(undefined),
    events: { addUserLoaded: vi.fn(), addUserUnloaded: vi.fn(), addAccessTokenExpired: vi.fn() },
    ...overrides,
  };
}

const TOKEN_USER = {
  access_token: 'header.payload.signature',
  profile: {
    sub: '11111111-2222-3333-4444-555555555555',
    preferred_username: 'olga.operator',
    email: 'olga.operator@example.test',
    name: 'Olga Operator',
    realm_access: { roles: ['operator', 'offline_access'] },
  },
};

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  window.history.replaceState({}, '', '/');
});

describe('completeRedirect', () => {
  it('does nothing when this page load is not a callback', async () => {
    const manager = fakeManager();
    const client = createAuthClient({ manager } as never);

    expect(await client.completeRedirect()).toBeNull();
    // Calling signinCallback on an ordinary load throws inside oidc-client-ts and would
    // surface as a broken app on every refresh.
    expect(manager.signinCallback).not.toHaveBeenCalled();
  });

  it('completes the flow when the realm has redirected back with a code', async () => {
    const manager = fakeManager({ signinCallback: vi.fn().mockResolvedValue(TOKEN_USER) });
    window.history.replaceState({}, '', '/?code=abc&state=xyz');
    const client = createAuthClient({ manager } as never);

    const session = await client.completeRedirect();

    expect(session).toMatchObject({ username: 'olga.operator', roles: ['operator'] });
    expect(client.accessToken()).toBe('header.payload.signature');
  });

  it('scrubs the code and state out of the address bar', async () => {
    const manager = fakeManager({ signinCallback: vi.fn().mockResolvedValue(TOKEN_USER) });
    window.history.replaceState({}, '', '/?code=abc&state=xyz');
    const client = createAuthClient({ manager } as never);

    await client.completeRedirect();

    // An authorization code left in the URL gets copied into chat messages and bookmarks.
    expect(window.location.search).toBe('');
  });

  it('keeps the hash route, because this app uses HashRouter', async () => {
    const manager = fakeManager({ signinCallback: vi.fn().mockResolvedValue(TOKEN_USER) });
    window.history.replaceState({}, '', '/?code=abc&state=xyz#/alarms');
    const client = createAuthClient({ manager } as never);

    await client.completeRedirect();

    expect(window.location.hash).toBe('#/alarms');
  });
});

describe('restore', () => {
  it('returns the session when the realm still has one', async () => {
    const manager = fakeManager({ signinSilent: vi.fn().mockResolvedValue(TOKEN_USER) });
    const client = createAuthClient({ manager } as never);

    expect(await client.restore()).toMatchObject({ username: 'olga.operator' });
  });

  it('returns null when the realm has no session, and does not redirect on its own', async () => {
    const manager = fakeManager({ signinSilent: vi.fn().mockRejectedValue(new Error('login_required')) });
    const client = createAuthClient({ manager } as never);

    expect(await client.restore()).toBeNull();
    // A module that redirected here would make the landing page unreachable for anybody who
    // is not signed in.
    expect(manager.signinRedirect).not.toHaveBeenCalled();
  });
});

describe('the token', () => {
  it('is never written to localStorage or sessionStorage', async () => {
    // Spec test 12. Asserted against the token string itself rather than a key name, so a
    // future change of storage key cannot make this pass while leaking.
    const manager = fakeManager({ signinCallback: vi.fn().mockResolvedValue(TOKEN_USER) });
    window.history.replaceState({}, '', '/?code=abc&state=xyz');
    const client = createAuthClient({ manager } as never);

    await client.completeRedirect();

    const dump = (storage: Storage) =>
      Object.keys(storage).map((k) => storage.getItem(k) ?? '').join('|');
    expect(dump(window.localStorage)).not.toContain('header.payload.signature');
    expect(dump(window.sessionStorage)).not.toContain('header.payload.signature');
  });

  it('is null before sign-in', () => {
    expect(createAuthClient({ manager: fakeManager() } as never).accessToken()).toBeNull();
  });

  it('is refreshed by a silent renew, and refresh reports failure rather than throwing', async () => {
    const renewed = { ...TOKEN_USER, access_token: 'renewed.token.value' };
    const manager = fakeManager({ signinSilent: vi.fn().mockResolvedValue(renewed) });
    const client = createAuthClient({ manager } as never);

    expect(await client.refresh()).toBe('renewed.token.value');
    expect(client.accessToken()).toBe('renewed.token.value');

    manager.signinSilent.mockRejectedValue(new Error('login_required'));
    expect(await client.refresh()).toBeNull();
  });
});

describe('signOut', () => {
  it('drops the in-memory token before leaving for the realm', async () => {
    const manager = fakeManager({ signinCallback: vi.fn().mockResolvedValue(TOKEN_USER) });
    window.history.replaceState({}, '', '/?code=abc&state=xyz');
    const client = createAuthClient({ manager } as never);
    await client.completeRedirect();

    await client.signOut();

    expect(client.accessToken()).toBeNull();
    expect(manager.signoutRedirect).toHaveBeenCalled();
  });
});

describe('onSession', () => {
  it('notifies listeners and can be unsubscribed', async () => {
    const manager = fakeManager({ signinCallback: vi.fn().mockResolvedValue(TOKEN_USER) });
    window.history.replaceState({}, '', '/?code=abc&state=xyz');
    const client = createAuthClient({ manager } as never);
    const seen: unknown[] = [];
    const stop = client.onSession((s) => seen.push(s));

    await client.completeRedirect();
    stop();
    await client.signOut();

    expect(seen).toHaveLength(1);
    expect(seen[0]).toMatchObject({ username: 'olga.operator' });
  });
});

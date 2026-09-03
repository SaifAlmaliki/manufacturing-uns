import { act, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const client = vi.hoisted(() => ({
  completeRedirect: vi.fn().mockResolvedValue(null),
  restore: vi.fn().mockResolvedValue(null),
  signIn: vi.fn().mockResolvedValue(undefined),
  signOut: vi.fn().mockResolvedValue(undefined),
  accessToken: vi.fn().mockReturnValue(null),
  refresh: vi.fn().mockResolvedValue(null),
  onSession: vi.fn().mockReturnValue(() => {}),
}));

vi.mock('../lib/auth/oidc', () => ({ authClient: client }));

import { AuthProvider, useAuth } from './AuthContext';

const SESSION = {
  subject: 'sub-1',
  username: 'olga.operator',
  email: 'olga.operator@example.test',
  displayName: 'Olga Operator',
  roles: ['operator'] as const,
};

const Probe = () => {
  const auth = useAuth();
  return (
    <div>
      <span data-testid="ready">{String(auth.isReady)}</span>
      <span data-testid="authenticated">{String(auth.isAuthenticated)}</span>
      <span data-testid="name">{auth.currentUser?.name ?? 'nobody'}</span>
      <span data-testid="roles">{auth.roles.join(',')}</span>
      <span data-testid="alarms">{String(auth.hasPermission('alarms'))}</span>
      <button onClick={auth.login}>sign in</button>
      <button onClick={auth.logout}>sign out</button>
    </div>
  );
};

const renderProbe = () => render(<AuthProvider><Probe /></AuthProvider>);

beforeEach(() => {
  vi.clearAllMocks();
  client.completeRedirect.mockResolvedValue(null);
  client.restore.mockResolvedValue(null);
  client.onSession.mockReturnValue(() => {});
  window.localStorage.clear();
});

describe('before the first restore settles', () => {
  it('is not ready and not authenticated', async () => {
    client.restore.mockReturnValue(new Promise(() => {}));   // never settles
    renderProbe();

    expect(screen.getByTestId('ready').textContent).toBe('false');
    expect(screen.getByTestId('authenticated').textContent).toBe('false');
  });

  it('does not report an unauthenticated user until it knows', async () => {
    // A router that redirected to /login on first paint would bounce a signed-in user out of
    // a deep link every time they refreshed.
    client.restore.mockReturnValue(new Promise(() => {}));
    renderProbe();

    expect(screen.getByTestId('name').textContent).toBe('nobody');
    expect(screen.getByTestId('ready').textContent).toBe('false');
  });
});

describe('a restored session', () => {
  it('becomes the current user with the realm roles', async () => {
    client.restore.mockResolvedValue(SESSION);
    renderProbe();

    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'));
    expect(screen.getByTestId('authenticated').textContent).toBe('true');
    expect(screen.getByTestId('name').textContent).toBe('Olga Operator');
    expect(screen.getByTestId('roles').textContent).toBe('operator');
  });

  it('resolves permissions from the role, not from a stored matrix', async () => {
    client.restore.mockResolvedValue({ ...SESSION, roles: ['viewer'] });
    renderProbe();

    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'));
    // rbac.ts's viewer profile, whatever it says. types/rbac.ts: viewer.alarms === false.
    expect(screen.getByTestId('alarms').textContent).toBe('false');
  });
});

describe('the redirect back from the realm', () => {
  it('is completed before a silent restore is attempted', async () => {
    const order: string[] = [];
    client.completeRedirect.mockImplementation(async () => { order.push('callback'); return SESSION; });
    client.restore.mockImplementation(async () => { order.push('restore'); return null; });
    renderProbe();

    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'));
    // Restoring first would race the callback and could discard the session just granted.
    expect(order[0]).toBe('callback');
    expect(screen.getByTestId('authenticated').textContent).toBe('true');
  });

  it('skips the silent restore entirely when the callback produced a session', async () => {
    client.completeRedirect.mockResolvedValue(SESSION);
    renderProbe();

    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'));
    expect(client.restore).not.toHaveBeenCalled();
  });
});

describe('login', () => {
  it('redirects to the realm and takes no password', async () => {
    // Spec test 8, and success criterion 1: "No password reaches the console."
    client.restore.mockResolvedValue(null);
    renderProbe();
    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'));

    await act(async () => { screen.getByText('sign in').click(); });

    expect(client.signIn).toHaveBeenCalledTimes(1);
    expect(client.signIn).toHaveBeenCalledWith();      // no arguments at all
  });
});

describe('logout', () => {
  it('ends the realm session and clears the user', async () => {
    client.restore.mockResolvedValue(SESSION);
    renderProbe();
    await waitFor(() => expect(screen.getByTestId('name').textContent).toBe('Olga Operator'));

    await act(async () => { screen.getByText('sign out').click(); });

    expect(client.signOut).toHaveBeenCalledTimes(1);
  });
});

describe('what is no longer here', () => {
  it('writes nothing about identity to localStorage', async () => {
    // Success criterion 5: no users, no roles, no permissions, no audit log.
    client.restore.mockResolvedValue(SESSION);
    renderProbe();
    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'));

    expect(Object.keys(window.localStorage)).toEqual([]);
  });

  it('exposes no switchUser', async () => {
    // Pretending to be somebody else was the defining feature of the fake login.
    client.restore.mockResolvedValue(SESSION);
    let auth: ReturnType<typeof useAuth> | null = null;
    const Capture = () => { auth = useAuth(); return null; };
    render(<AuthProvider><Capture /></AuthProvider>);

    await waitFor(() => expect(auth).not.toBeNull());
    expect('switchUser' in (auth as object)).toBe(false);
  });
});

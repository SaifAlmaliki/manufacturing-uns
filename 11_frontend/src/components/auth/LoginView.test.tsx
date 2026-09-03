import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

const login = vi.fn();
vi.mock('../../context/AuthContext', () => ({
  useAuth: () => ({
    login,
    logout: vi.fn(),
    isAuthenticated: false,
    isReady: true,
    currentUser: null,
    roles: [],
    hasPermission: () => false,
  }),
}));

import { LoginView } from './LoginView';

const renderLogin = () => render(<MemoryRouter><LoginView /></MemoryRouter>);

describe('the sign-in screen', () => {
  it('has no password field', () => {
    // Spec section 6: "The LoginView password field is deleted rather than wired up - the
    // console must never see a password." Queried by input type, because a field renamed to
    // "PIN" would still be a password.
    const { container } = renderLogin();

    expect(container.querySelector('input[type="password"]')).toBeNull();
  });

  it('has no fields at all — signing in is one button', () => {
    const { container } = renderLogin();

    expect(container.querySelectorAll('input')).toHaveLength(0);
    expect(container.querySelectorAll('select')).toHaveLength(0);
  });

  it('sends the user to the realm', async () => {
    renderLogin();

    screen.getByTestId('sign-in').click();

    expect(login).toHaveBeenCalledTimes(1);
  });

  it('names where sign-in happens, so an unreachable realm is diagnosable', () => {
    // Failure modes table: "The console says the identity provider is unreachable and names
    // the URL." Naming it up front means the failure needs no extra screen.
    const { container } = renderLogin();

    expect(container.textContent).toContain('Keycloak');
  });

  it('offers no demo identities', () => {
    // The five seeded accounts in AuthContext are gone; a picker for them would be a picker
    // for nothing.
    const { container } = renderLogin();

    expect(container.textContent).not.toContain('Demo');
    expect(container.textContent).not.toContain('1-Click');
  });
});

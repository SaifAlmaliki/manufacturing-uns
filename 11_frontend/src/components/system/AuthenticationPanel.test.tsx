import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../../context/AuthContext', () => ({
  useAuth: () => ({
    session: { subject: 's', username: 'erin', displayName: 'Erin Engineer', roles: ['engineer'] },
    isAuthenticated: true,
  }),
}));

import { AuthenticationPanel } from './AuthenticationPanel';

describe('AuthenticationPanel', () => {
  it('says exactly what is protected and what is not', () => {
    const { container } = render(<AuthenticationPanel />);
    const text = container.textContent?.replace(/\s+/g, ' ') ?? '';

    expect(text).toContain(
      'Sign-in protects the console and the GraphQL read surface. The MQTT broker, the graph ' +
        'database, the historian and the Kafka broker have no authentication on this deployment.',
    );
  });

  it('names the realm, so an integrator can find it', () => {
    const { container } = render(<AuthenticationPanel />);

    expect(container.textContent).toContain('/auth/realms/uns');
  });

  it('shows who is signed in and with which roles', () => {
    render(<AuthenticationPanel />);

    expect(screen.getByText(/Erin Engineer/)).toBeTruthy();
    expect(screen.getByText(/Plant Engineer/)).toBeTruthy();
  });
});

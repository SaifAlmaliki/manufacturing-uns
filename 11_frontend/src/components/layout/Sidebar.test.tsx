import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../../context/AuthContext', () => ({
  useAuth: () => ({
    currentUser: {
      id: '1',
      name: 'Ada Admin',
      email: 'admin.user@example.test',
      role: 'admin',
    },
    canAccessTab: () => ({ allowed: true, requiredFeature: 'uns_tree', featureName: 'UNS' }),
    isAdmin: true,
  }),
}));
vi.mock('../../context/UNSContext', () => ({
  useUNS: () => ({
    settings: { organization: 'HajabjaWTP' },
    health: { status: 'LIVE' },
  }),
}));
vi.mock('../../context/AlarmContext', () => ({
  useAlarms: () => ({ myUnacknowledgedCount: 0 }),
}));

import { Sidebar } from './Sidebar';

const noop = () => undefined;

function renderSidebar() {
  return render(
    <MemoryRouter>
      <Sidebar
        isCollapsed={false}
        onToggleCollapse={noop}
        isMobileOpen={false}
        onCloseMobile={noop}
      />
    </MemoryRouter>,
  );
}

describe('Sidebar chrome', () => {
  it('does not offer a Streams menu item', () => {
    renderSidebar();
    expect(screen.queryByRole('link', { name: /streams/i })).toBeNull();
    expect(screen.queryByText('Streams')).toBeNull();
  });

  it('does not render the signed-in profile in the left menu', () => {
    renderSidebar();
    const menu = document.getElementById('application-left-menu');
    expect(menu).toBeTruthy();
    expect(menu?.querySelector('#user-session-trigger')).toBeNull();
    expect(screen.queryByRole('button', { name: /account menu/i })).toBeNull();
    expect(screen.queryByText('Ada Admin')).toBeNull();
    expect(screen.getByRole('button', { name: /collapse sidebar/i })).toBeTruthy();
  });
});

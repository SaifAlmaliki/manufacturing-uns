import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const auth = vi.hoisted(() => ({
  currentUser: {
    id: '1',
    name: 'Ada Admin',
    email: 'admin.user@example.test',
    role: 'admin' as const,
    department: '',
    plantLocation: '',
    status: 'active' as const,
    createdAt: '',
    lastLogin: '',
    customPermissions: {},
  } as {
    id: string;
    name: string;
    email: string;
    role: 'admin';
    department: string;
    plantLocation: string;
    status: 'active';
    createdAt: string;
    lastLogin: string;
    customPermissions: Record<string, boolean>;
  } | null,
  isAdmin: true,
  hasPermission: () => true,
  logout: vi.fn(),
}));

vi.mock('../../context/AuthContext', () => ({ useAuth: () => auth }));
vi.mock('../../context/UNSContext', () => ({
  useUNS: () => ({ staleNodesCount: 0, bookmarks: [], setActiveTab: vi.fn() }),
}));
vi.mock('../../context/AlarmContext', () => ({
  useAlarms: () => ({ myUnacknowledgedCount: 0 }),
}));
vi.mock('../../context/ThemeContext', () => ({
  useTheme: () => ({ isDark: false, toggleTheme: vi.fn() }),
}));

import { Header } from './Header';

const noop = () => undefined;

function renderHeader(onOpenCopilot = noop) {
  return render(
    <MemoryRouter>
      <Header
        onOpenCopilot={onOpenCopilot}
        onOpenBookmarks={noop}
        onOpenStaleDrawer={noop}
        onToggleMobileSidebar={noop}
      />
    </MemoryRouter>,
  );
}

function renderHeaderLegacy() {
  return renderHeader();
}

beforeEach(() => {
  auth.currentUser = {
    id: '1',
    name: 'Ada Admin',
    email: 'admin.user@example.test',
    role: 'admin',
    department: '',
    plantLocation: '',
    status: 'active',
    createdAt: '',
    lastLogin: '',
    customPermissions: {},
  };
});

describe('Header signed-in name', () => {
  it('shows the logged-in username in the top-right chrome', () => {
    renderHeaderLegacy();
    expect(screen.getByRole('button', { name: /Ada Admin/ })).toBeTruthy();
  });

  it('does not show an account chip when nobody is signed in', () => {
    auth.currentUser = null;
    renderHeaderLegacy();
    expect(screen.queryByRole('button', { name: /account menu/i })).toBeNull();
    expect(screen.queryByText('Ada Admin')).toBeNull();
  });

  it('shows the Factory Copilot control', () => {
    renderHeaderLegacy();
    expect(screen.getByLabelText('Factory Copilot')).toBeTruthy();
  });
});

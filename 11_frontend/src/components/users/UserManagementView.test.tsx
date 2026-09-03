import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const fetchRealmMembers = vi.hoisted(() => vi.fn());
vi.mock('../../lib/auth/directory', () => ({ fetchRealmMembers }));

const auth = vi.hoisted(() => ({
  isAdmin: true,
  roles: ['admin'] as ('admin' | 'operator')[],
  currentUser: null as null,
  hasPermission: () => true,
}));
vi.mock('../../context/AuthContext', () => ({ useAuth: () => auth }));

import { UserManagementView } from './UserManagementView';

beforeEach(() => {
  vi.clearAllMocks();
  auth.isAdmin = true;
  auth.roles = ['admin'];
});

const MEMBERS = {
  kind: 'members' as const,
  members: [
    {
      id: 'kc-1',
      username: 'erin',
      email: 'erin@example.test',
      displayName: 'Erin Engineer',
      enabled: true,
      roles: ['engineer' as const],
    },
    {
      id: 'kc-2',
      username: 'olga',
      displayName: 'Olga Operator',
      enabled: false,
      roles: [] as const,
    },
  ],
};

describe('the user directory', () => {
  it('lists the realm’s members with the roles the realm granted', async () => {
    fetchRealmMembers.mockResolvedValue(MEMBERS);
    render(<UserManagementView />);

    await waitFor(() => expect(screen.getByText('Erin Engineer')).toBeTruthy());
    expect(screen.getByText('Olga Operator')).toBeTruthy();
    expect(screen.getByText(/Plant Engineer/i)).toBeTruthy();
  });

  it('shows a member with no console role as having none, not as a viewer', async () => {
    fetchRealmMembers.mockResolvedValue(MEMBERS);
    render(<UserManagementView />);

    await waitFor(() => expect(screen.getByText('Olga Operator')).toBeTruthy());
    expect(screen.getAllByText(/No console role/i).length).toBeGreaterThan(0);
  });

  it('says it cannot read the realm rather than showing an empty directory', async () => {
    fetchRealmMembers.mockResolvedValue({ kind: 'forbidden' });
    render(<UserManagementView />);

    await waitFor(() => expect(screen.getByText(/cannot read the realm/i)).toBeTruthy());
    expect(screen.queryByText(/no users/i)).toBeNull();
  });

  it('names where users are actually managed', async () => {
    fetchRealmMembers.mockResolvedValue({ kind: 'forbidden' });
    render(<UserManagementView />);

    await waitFor(() => expect(screen.getByText(/Keycloak/)).toBeTruthy());
  });

  it('reports an unreachable realm with its reason', async () => {
    fetchRealmMembers.mockResolvedValue({ kind: 'unreachable', detail: 'Failed to fetch' });
    render(<UserManagementView />);

    await waitFor(() => expect(screen.getByText(/Failed to fetch/)).toBeTruthy());
  });

  it('does not ask the realm at all when the signed-in user is not an admin', async () => {
    auth.isAdmin = false;
    auth.roles = ['operator'];
    render(<UserManagementView />);

    await waitFor(() => expect(screen.getByText(/administrator/i)).toBeTruthy());
    expect(fetchRealmMembers).not.toHaveBeenCalled();
  });
});

describe('what this screen can no longer do', () => {
  it('offers no way to create, edit or delete a user', async () => {
    fetchRealmMembers.mockResolvedValue(MEMBERS);
    const { container } = render(<UserManagementView />);

    await waitFor(() => expect(screen.getByText('Erin Engineer')).toBeTruthy());
    expect(container.textContent).not.toMatch(/add user|new user|create user|delete user/i);
  });

  it('offers no per-user permission tick boxes', async () => {
    fetchRealmMembers.mockResolvedValue(MEMBERS);
    const { container } = render(<UserManagementView />);

    await waitFor(() => expect(screen.getByText('Erin Engineer')).toBeTruthy());
    expect(container.querySelectorAll('input[type="checkbox"]')).toHaveLength(0);
  });
});

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const fetchRealmMembers = vi.hoisted(() => vi.fn());
vi.mock('../../lib/auth/directory', () => ({ fetchRealmMembers }));

const getAccessGroups = vi.hoisted(() => vi.fn());
const getAssets = vi.hoisted(() => vi.fn());
const saveAccessGroup = vi.hoisted(() => vi.fn());
const setAccessGroupMembers = vi.hoisted(() => vi.fn());
vi.mock('../../services/graphql/client', () => ({
  unsGraphQLClient: {
    getAccessGroups,
    getAssets,
    saveAccessGroup,
    deleteAccessGroup: vi.fn(),
    setAccessGroupMembers,
  },
}));

const auth = vi.hoisted(() => ({
  isAdmin: true,
  roles: ['admin'] as ('admin' | 'operator')[],
  currentUser: null as null,
  hasPermission: () => true,
}));
vi.mock('../../context/AuthContext', () => ({ useAuth: () => auth }));

import { UserManagementView } from './UserManagementView';

const FILTRATION_GROUP = {
  id: 1,
  name: 'Filtration',
  roots: [{ path: 'AcmeWater/Site1/Filtration', segment: 'Filtration', level: 'AREA', assetId: 9 }],
  subjects: ['kc-1'],
};

beforeEach(() => {
  vi.clearAllMocks();
  auth.isAdmin = true;
  auth.roles = ['admin'];
  getAccessGroups.mockResolvedValue([FILTRATION_GROUP]);
  getAssets.mockResolvedValue([]);
  saveAccessGroup.mockResolvedValue(FILTRATION_GROUP);
  setAccessGroupMembers.mockResolvedValue(FILTRATION_GROUP);
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

  it('offers Open Keycloak as a button', async () => {
    fetchRealmMembers.mockResolvedValue({ kind: 'forbidden' });
    render(<UserManagementView />);
    await waitFor(() => expect(screen.getByRole('button', { name: /Open Keycloak/i })).toBeTruthy());
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

  it('shows Access Group chips on a directory row', async () => {
    fetchRealmMembers.mockResolvedValue(MEMBERS);
    render(<UserManagementView />);
    await waitFor(() => expect(screen.getByText('Erin Engineer')).toBeTruthy());
    expect(screen.getByText('Filtration')).toBeTruthy();
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
    render(<UserManagementView />);

    await waitFor(() => expect(screen.getByText('Erin Engineer')).toBeTruthy());
    const directoryTable = screen.getByRole('table');
    expect(directoryTable.querySelectorAll('input[type="checkbox"]')).toHaveLength(0);
  });
});

describe('Access Groups on Users and Access', () => {
  it('offers Assign groups, Create group and Save group after groups load', async () => {
    fetchRealmMembers.mockResolvedValue(MEMBERS);
    render(<UserManagementView />);

    await waitFor(() => expect(screen.getByText('Erin Engineer')).toBeTruthy());
    expect(screen.getAllByRole('button', { name: /Assign groups/i }).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole('button', { name: /Access Groups/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /Create group/i })).toBeTruthy());

    fireEvent.click(screen.getByRole('button', { name: /Create group/i }));
    expect(screen.getByRole('button', { name: /Save group/i })).toBeTruthy();
    await waitFor(() => expect(getAssets).toHaveBeenCalled());
  });

  it('saves Assign groups by calling setAccessGroupMembers once per group', async () => {
    const packaging = {
      id: 2,
      name: 'Packaging',
      roots: [{ path: 'AcmeWater/Site1/Packaging', segment: 'Packaging', level: 'AREA', assetId: 10 }],
      subjects: [] as string[],
    };
    getAccessGroups.mockResolvedValue([FILTRATION_GROUP, packaging]);
    fetchRealmMembers.mockResolvedValue(MEMBERS);
    render(<UserManagementView />);

    await waitFor(() => expect(screen.getByText('Erin Engineer')).toBeTruthy());
    await waitFor(() => expect(screen.getByText('Filtration')).toBeTruthy());
    fireEvent.click(screen.getAllByRole('button', { name: /Assign groups/i })[0]);
    await waitFor(() => expect(screen.getByText('Packaging')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /^Save$/i }));

    await waitFor(() => expect(setAccessGroupMembers).toHaveBeenCalledTimes(2));
    expect(setAccessGroupMembers).toHaveBeenCalledWith(1, ['kc-1']);
    expect(setAccessGroupMembers).toHaveBeenCalledWith(2, []);
  });

  it('treats a parent tick as covering descendants without ticking children', async () => {
    getAssets.mockResolvedValue([
      { id: 1, path: 'AcmeWater', segment: 'AcmeWater', level: 'ENTERPRISE' },
      { id: 2, path: 'AcmeWater/Site1', segment: 'Site1', level: 'SITE' },
      { id: 9, path: 'AcmeWater/Site1/Filtration', segment: 'Filtration', level: 'AREA' },
    ]);
    fetchRealmMembers.mockResolvedValue(MEMBERS);
    render(<UserManagementView />);

    fireEvent.click(screen.getByRole('button', { name: /Access Groups/i }));
    fireEvent.click(await screen.findByRole('button', { name: /Create group/i }));

    const parent = await screen.findByRole('checkbox', { name: 'AcmeWater' });
    const child = screen.getByRole('checkbox', { name: 'AcmeWater/Site1' });
    const grandchild = screen.getByRole('checkbox', { name: 'AcmeWater/Site1/Filtration' });

    fireEvent.click(parent);

    expect(parent).toBeChecked();
    expect(child).toBeChecked();
    expect(child).toBeDisabled();
    expect(grandchild).toBeChecked();
    expect(grandchild).toBeDisabled();
  });

  it('sets editor id from the saved group before members so a retry does not create a duplicate', async () => {
    const created = {
      id: 99,
      name: 'New zone',
      roots: [{ path: 'AcmeWater/Site1/Filtration', segment: 'Filtration', level: 'AREA', assetId: 9 }],
      subjects: [] as string[],
    };
    getAssets.mockResolvedValue([
      { id: 9, path: 'AcmeWater/Site1/Filtration', segment: 'Filtration', level: 'AREA' },
    ]);
    saveAccessGroup.mockResolvedValue(created);
    setAccessGroupMembers.mockRejectedValueOnce(new Error('members failed'));
    fetchRealmMembers.mockResolvedValue(MEMBERS);
    render(<UserManagementView />);

    fireEvent.click(screen.getByRole('button', { name: /Access Groups/i }));
    fireEvent.click(await screen.findByRole('button', { name: /Create group/i }));
    fireEvent.change(screen.getByPlaceholderText(/Access Group name/i), {
      target: { value: 'New zone' },
    });
    fireEvent.click(await screen.findByRole('checkbox', { name: 'AcmeWater/Site1/Filtration' }));
    fireEvent.click(screen.getByRole('button', { name: /Save group/i }));

    await waitFor(() => expect(saveAccessGroup).toHaveBeenCalledWith('New zone', [9], null));
    await waitFor(() => expect(setAccessGroupMembers).toHaveBeenCalledWith(99, []));
    await waitFor(() => expect(screen.getByText('members failed')).toBeTruthy());

    setAccessGroupMembers.mockResolvedValueOnce(created);
    fireEvent.click(screen.getByRole('button', { name: /Save group/i }));

    await waitFor(() => expect(saveAccessGroup).toHaveBeenCalledWith('New zone', [9], 99));
  });

  it('reloads groups when Assign save fails so retry is not from a stale snapshot', async () => {
    fetchRealmMembers.mockResolvedValue(MEMBERS);
    setAccessGroupMembers.mockRejectedValueOnce(new Error('assign failed'));
    render(<UserManagementView />);

    await waitFor(() => expect(screen.getByText('Erin Engineer')).toBeTruthy());
    fireEvent.click(screen.getAllByRole('button', { name: /Assign groups/i })[0]);
    fireEvent.click(await screen.findByRole('button', { name: /^Save$/i }));

    await waitFor(() => expect(screen.getByText('assign failed')).toBeTruthy());
    await waitFor(() => expect(getAccessGroups).toHaveBeenCalledTimes(2));
  });

  it('lists member ids not in the realm as unknown and removable', async () => {
    getAccessGroups.mockResolvedValue([
      { ...FILTRATION_GROUP, subjects: ['kc-1', 'stale-sub'] },
    ]);
    fetchRealmMembers.mockResolvedValue(MEMBERS);
    render(<UserManagementView />);

    fireEvent.click(screen.getByRole('button', { name: /Access Groups/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^Edit$/i }));

    await waitFor(() => expect(screen.getByText('unknown')).toBeTruthy());
    expect(screen.getByText('stale-sub')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: /Remove unknown stale-sub/i }));
    expect(screen.queryByText('unknown')).toBeNull();
    expect(screen.queryByText('stale-sub')).toBeNull();
  });
});

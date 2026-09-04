import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const getHierarchy = vi.hoisted(() => vi.fn());
const saveHierarchy = vi.hoisted(() => vi.fn());
const retryHierarchyMigrate = vi.hoisted(() => vi.fn());
vi.mock('../../services/graphql/client', () => ({
  unsGraphQLClient: { getHierarchy, saveHierarchy, retryHierarchyMigrate },
}));

const auth = vi.hoisted(() => ({
  hasPermission: (feature: string): boolean => feature === 'settings_edit',
  isAdmin: true,
  roles: ['admin'] as ('admin' | 'operator')[],
  currentUser: null as null,
}));
vi.mock('../../context/AuthContext', () => ({ useAuth: () => auth }));

const uns = vi.hoisted(() => ({ updateSettings: vi.fn() }));
vi.mock('../../context/UNSContext', () => ({ useUNS: () => uns }));

import { HierarchyView } from './HierarchyView';

const TREE = {
  enterprise: 'AcmeWater',
  sites: [
    {
      name: 'Site1',
      areas: [
        {
          name: 'RawWater',
          kind: 'production',
          lines: [{ name: 'Train1', cells: ['V101'] }],
        },
      ],
    },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  auth.hasPermission = (feature: string): boolean => feature === 'settings_edit';
  auth.isAdmin = true;
  auth.roles = ['admin'];
  getHierarchy.mockResolvedValue(TREE);
  saveHierarchy.mockResolvedValue({
    tree: TREE,
    job: { status: 'done', oldPrefix: null, newPrefix: null, rewritten: 0, error: null },
  });
  retryHierarchyMigrate.mockResolvedValue({
    status: 'done',
    oldPrefix: 'AcmeWater',
    newPrefix: 'Contoso',
    rewritten: 3,
    error: null,
  });
});

describe('access', () => {
  it('shows AccessRestricted when the signed-in role cannot edit settings', async () => {
    auth.hasPermission = (_feature: string): boolean => false;
    auth.isAdmin = false;
    auth.roles = ['operator'];
    render(<HierarchyView />);

    await waitFor(() => expect(screen.getByText(/permission required/i)).toBeTruthy());
    expect(getHierarchy).not.toHaveBeenCalled();
  });
});

describe('the plant hierarchy editor', () => {
  it('loads the tree and shows the simulator banner', async () => {
    render(<HierarchyView />);

    await waitFor(() => expect(screen.getByRole('button', { name: 'Enterprise AcmeWater' })).toBeTruthy());
    expect(screen.getByText(/simulator still publishes the shipped WTP paths/i)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Site Site1' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Cell V101' })).toBeTruthy();
  });

  it('does not fetch the tree when access is denied', async () => {
    auth.hasPermission = (_feature: string): boolean => false;
    render(<HierarchyView />);
    await waitFor(() => expect(screen.getByText(/permission required/i)).toBeTruthy());
    expect(getHierarchy).not.toHaveBeenCalled();
  });

  it('sends the committed rename prefixes on Save', async () => {
    render(<HierarchyView />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Enterprise AcmeWater' })).toBeTruthy());

    const nameInput = screen.getByLabelText('Name');
    fireEvent.change(nameInput, { target: { value: 'Contoso' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(saveHierarchy).toHaveBeenCalledTimes(1));
    expect(saveHierarchy).toHaveBeenCalledWith(
      expect.objectContaining({ enterprise: 'Contoso' }),
      [{ oldPrefix: 'AcmeWater', newPrefix: 'Contoso' }],
    );
  });

  it('refreshes the sidebar organization from the saved enterprise', async () => {
    saveHierarchy.mockResolvedValue({
      tree: { ...TREE, enterprise: 'Contoso' },
      job: { status: 'done', oldPrefix: 'AcmeWater', newPrefix: 'Contoso', rewritten: 0, error: null },
    });
    render(<HierarchyView />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Enterprise AcmeWater' })).toBeTruthy());

    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Contoso' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(uns.updateSettings).toHaveBeenCalledWith({ organization: 'Contoso' }));
  });

  it('shows migrate job status after save and retries a failed job', async () => {
    saveHierarchy.mockResolvedValue({
      tree: { ...TREE, enterprise: 'Contoso' },
      job: { status: 'failed', oldPrefix: 'AcmeWater', newPrefix: 'Contoso', rewritten: 0, error: 'migrate exploded' },
    });
    render(<HierarchyView />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Enterprise AcmeWater' })).toBeTruthy());

    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Contoso' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(screen.getByText(/migrate job/i)).toBeTruthy());
    expect(screen.getByText(/failed/i)).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(retryHierarchyMigrate).toHaveBeenCalledTimes(1));
  });

  it('adds only the next legal child level', async () => {
    render(<HierarchyView />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Enterprise AcmeWater' })).toBeTruthy());

    fireEvent.click(screen.getByRole('button', { name: 'Add child' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Site Site' })).toBeTruthy());

    fireEvent.click(screen.getByRole('button', { name: 'Cell V101' }));
    expect(screen.getByRole('button', { name: 'Add child' })).toBeDisabled();
  });
});

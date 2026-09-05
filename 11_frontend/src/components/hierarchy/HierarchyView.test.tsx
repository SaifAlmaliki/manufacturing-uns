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
          lines: [{ name: 'Train1', cells: [{ name: 'V101', machines: [] }] }],
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
    expect(screen.getByText(/old graph branch reappears/i)).toBeTruthy();
    expect(screen.getByText(/durable only after the publisher is retargeted/i)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Site Site1' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Cell V101' })).toBeTruthy();
  });

  it('does not fetch the tree when access is denied', async () => {
    auth.hasPermission = (_feature: string): boolean => false;
    render(<HierarchyView />);
    await waitFor(() => expect(screen.getByText(/permission required/i)).toBeTruthy());
    expect(getHierarchy).not.toHaveBeenCalled();
  });

  it('sends a single site-level rename after renaming a cell then its site', async () => {
    render(<HierarchyView />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Enterprise AcmeWater' })).toBeTruthy());

    fireEvent.click(screen.getByRole('button', { name: 'Cell V101' }));
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'V9' } });
    fireEvent.click(screen.getByRole('button', { name: 'Site Site1' }));

    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Nord' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(saveHierarchy).toHaveBeenCalledTimes(1));
    expect(saveHierarchy).toHaveBeenCalledWith(
      expect.objectContaining({
        enterprise: 'AcmeWater',
        sites: [expect.objectContaining({ name: 'Nord' })],
      }),
      [{ oldPrefix: 'AcmeWater/Site1', newPrefix: 'AcmeWater/Nord' }],
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

  it('offers Line, Cell, and Machine under an Area from both New menus', async () => {
    render(<HierarchyView />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Area RawWater' })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Area RawWater' }));
    const news = screen.getAllByRole('button', { name: 'New' });
    expect(news).toHaveLength(2);
    fireEvent.click(news[0]);
    expect(screen.getByRole('menuitem', { name: /^Machine/ })).toBeTruthy();
    expect(screen.getByRole('menuitem', { name: /^Line/ })).toBeTruthy();
  });

  it('does not clip the tree-header New menu on the plant card', async () => {
    render(<HierarchyView />);
    await waitFor(() => expect(screen.getByText('Plant tree')).toBeTruthy());
    const card = screen.getByText('Plant tree').parentElement?.parentElement;
    expect(card?.className ?? '').not.toMatch(/overflow-hidden/);
  });

  it('creates a Cell and Machine under a Line and selects the Machine', async () => {
    render(<HierarchyView />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Line Train1' })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Line Train1' }));
    fireEvent.click(screen.getAllByRole('button', { name: 'New' })[1]);
    fireEvent.click(screen.getByRole('menuitem', { name: /^Machine/ }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Machine Machine' })).toBeTruthy());
    expect(screen.getByRole('button', { name: 'Cell Cell' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Machine Machine' })).toHaveAttribute(
      'aria-current',
      'true',
    );
    expect(screen.getByLabelText('Name')).toHaveValue('Machine');
  });

  it('disables New after adding a Machine under a Cell', async () => {
    render(<HierarchyView />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Cell V101' })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Cell V101' }));
    fireEvent.click(screen.getAllByRole('button', { name: 'New' })[1]);
    fireEvent.click(screen.getByRole('menuitem', { name: /^Machine/ }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Machine Machine' })).toBeTruthy());
    for (const button of screen.getAllByRole('button', { name: 'New' })) {
      expect(button).toBeDisabled();
    }
  });

  it('saves an authored machine on the cell', async () => {
    render(<HierarchyView />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Cell V101' })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Cell V101' }));
    fireEvent.click(screen.getAllByRole('button', { name: 'New' })[1]);
    fireEvent.click(screen.getByRole('menuitem', { name: /^Machine/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(saveHierarchy).toHaveBeenCalledTimes(1));
    expect(saveHierarchy).toHaveBeenCalledWith(
      expect.objectContaining({
        sites: [
          expect.objectContaining({
            areas: [
              expect.objectContaining({
                lines: [
                  expect.objectContaining({
                    cells: [
                      expect.objectContaining({
                        name: 'V101',
                        machines: ['Machine'],
                      }),
                    ],
                  }),
                ],
              }),
            ],
          }),
        ],
      }),
      [],
    );
  });

  it('shows the Machine type word on a Machine row, not M', async () => {
    getHierarchy.mockResolvedValue({
      ...TREE,
      sites: [
        {
          name: 'Site1',
          areas: [
            {
              name: 'RawWater',
              kind: 'production',
              lines: [{ name: 'Train1', cells: [{ name: 'V101', machines: ['Dryer'] }] }],
            },
          ],
        },
      ],
    });
    render(<HierarchyView />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Machine Dryer' })).toBeTruthy());
    const row = screen.getByRole('button', { name: 'Machine Dryer' });
    expect(row).toHaveTextContent('Machine');
    expect(row).toHaveTextContent('Dryer');
    expect(row.textContent).not.toMatch(/^\s*M\s/);
  });
});

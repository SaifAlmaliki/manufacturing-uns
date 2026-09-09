import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const getHierarchy = vi.hoisted(() => vi.fn());
const saveHierarchy = vi.hoisted(() => vi.fn());
const retryHierarchyMigrate = vi.hoisted(() => vi.fn());
const getSubscribedSignals = vi.hoisted(() => vi.fn());
const getAssets = vi.hoisted(() => vi.fn());
const updateConnectivityTag = vi.hoisted(() => vi.fn());
vi.mock('../../services/graphql/client', () => ({
  unsGraphQLClient: {
    getHierarchy,
    saveHierarchy,
    retryHierarchyMigrate,
    getSubscribedSignals,
    getAssets,
    updateConnectivityTag,
  },
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
  getSubscribedSignals.mockResolvedValue([]);
  getAssets.mockResolvedValue([]);
  updateConnectivityTag.mockResolvedValue({});
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
  it('loads the tree without the simulator retarget banner', async () => {
    render(<HierarchyView />);

    await waitFor(() => expect(screen.getByRole('button', { name: 'Enterprise AcmeWater' })).toBeTruthy());
    expect(screen.queryByText(/simulator still publishes the shipped WTP paths/i)).toBeNull();
    expect(screen.queryByText(/durable only after the publisher is retargeted/i)).toBeNull();
    expect(screen.getByRole('button', { name: 'Site Site1' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Cell V101' })).toBeTruthy();
    expect(screen.getByRole('separator', { name: /resize plant tree/i })).toBeTruthy();
  });

  it('asks for confirmation before removing a node', async () => {
    render(<HierarchyView />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Cell V101' })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Cell V101' }));
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }));

    expect(screen.getByRole('dialog', { name: /remove this cell/i })).toBeTruthy();
    expect(screen.getByText(/V101 and anything under it/i)).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog', { name: /remove this cell/i })).toBeNull();
    expect(screen.getByRole('button', { name: 'Cell V101' })).toBeTruthy();
  });

  it('removes the node only after confirm', async () => {
    render(<HierarchyView />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Cell V101' })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Cell V101' }));
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));

    expect(screen.queryByRole('button', { name: 'Cell V101' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Line Train1' })).toBeTruthy();
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

  it('saves a renamed new machine without a migrate rename', async () => {
    render(<HierarchyView />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Cell V101' })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Cell V101' }));
    fireEvent.click(screen.getAllByRole('button', { name: 'New' })[1]);
    fireEvent.click(screen.getByRole('menuitem', { name: /^Machine/ }));
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Machine01' } });
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
                        machines: ['Machine01'],
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

  it('collapses and expands a parent the way the condition-monitoring tree does', async () => {
    render(<HierarchyView />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Cell V101' })).toBeTruthy());

    fireEvent.click(screen.getByRole('button', { name: 'Collapse Site Site1' }));
    expect(screen.queryByRole('button', { name: 'Area RawWater' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Cell V101' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Site Site1' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Expand Site Site1' })).toHaveAttribute(
      'aria-expanded',
      'false',
    );

    fireEvent.click(screen.getByRole('button', { name: 'Expand Site Site1' }));
    expect(screen.getByRole('button', { name: 'Area RawWater' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Cell V101' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Collapse Site Site1' })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
  });

  it('keeps the current selection when only the chevron is clicked', async () => {
    render(<HierarchyView />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Cell V101' })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Cell V101' }));
    expect(screen.getByLabelText('Name')).toHaveValue('V101');

    fireEvent.click(screen.getByRole('button', { name: 'Collapse Line Train1' }));
    expect(screen.getByLabelText('Name')).toHaveValue('V101');
    expect(screen.queryByRole('button', { name: 'Cell V101' })).toBeNull();
  });

  it('does not offer a chevron on a leaf Machine', async () => {
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
    expect(screen.queryByRole('button', { name: /Collapse Machine Dryer/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /Expand Machine Dryer/ })).toBeNull();
  });

  it('opens collapsed ancestors when a child is added under them', async () => {
    render(<HierarchyView />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Line Train1' })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Line Train1' }));
    fireEvent.click(screen.getByRole('button', { name: 'Collapse Line Train1' }));
    expect(screen.queryByRole('button', { name: 'Cell V101' })).toBeNull();
    fireEvent.click(screen.getAllByRole('button', { name: 'New' })[1]);
    fireEvent.click(screen.getByRole('menuitem', { name: /^Cell/ }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Cell Cell' })).toBeTruthy());
    expect(screen.getByRole('button', { name: 'Cell V101' })).toBeTruthy();
  });

  it('marks plant nodes green when a subscribed signal is connected under them', async () => {
    getHierarchy.mockResolvedValue({
      ...TREE,
      sites: [
        TREE.sites[0],
        { name: 'Site2', areas: [{ name: 'Treatment', kind: 'production', lines: [] }] },
      ],
    });
    getSubscribedSignals.mockResolvedValue([
      {
        serverId: 's1',
        serverName: 'opcplc',
        nodeId: 'ns=3;s=V101',
        browsePath: 'V101/Level',
        displayName: 'Level',
        mqttTopic: 'AcmeWater/Site1/RawWater/Train1/V101/Level',
        subscribed: true,
      },
    ]);
    render(<HierarchyView />);
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Cell V101' }).querySelector('[aria-label="Signals connected"]'),
      ).toBeTruthy(),
    );

    expect(screen.getByRole('button', { name: 'Site Site1' }).querySelector('[aria-label="Signals connected"]')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Enterprise AcmeWater' }).querySelector('[aria-label="Signals connected"]')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Site Site2' }).querySelector('[aria-label="Signals connected"]')).toBeNull();
    expect(screen.getByRole('button', { name: 'Area Treatment' }).querySelector('[aria-label="Signals connected"]')).toBeNull();
  });

  it('lets the plant tree fill the card instead of clipping the last node with reserved bottom space', async () => {
    render(<HierarchyView />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Enterprise AcmeWater' })).toBeTruthy());
    const scroller = screen.getByRole('button', { name: 'Enterprise AcmeWater' }).closest('.overflow-y-auto');
    expect(scroller).toBeTruthy();
    expect(scroller?.className ?? '').not.toMatch(/max-h-\[calc\(100vh-22rem\)\]/);
    expect(scroller?.className ?? '').toMatch(/flex-1/);
    expect(scroller?.className ?? '').not.toMatch(/\bp-2\b/);
  });

  it('opens a signal picker from the control in front of a tree node without changing selection', async () => {
    getSubscribedSignals.mockResolvedValue([
      {
        serverId: 's1',
        serverName: 'opcplc',
        nodeId: 'ns=3;s=T101',
        browsePath: 'T101/Level',
        displayName: 'Level',
        mqttTopic: 'Plant/T101/Level',
        subscribed: true,
      },
    ]);
    render(<HierarchyView />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Attach signals to Cell V101' })).toBeTruthy());
    expect(screen.getByLabelText('Name')).toHaveValue('AcmeWater');

    fireEvent.click(screen.getByRole('button', { name: 'Attach signals to Cell V101' }));
    expect(screen.getByRole('dialog', { name: /attach signals to cell v101/i })).toBeTruthy();
    expect(screen.getByRole('checkbox', { name: /level/i })).toBeTruthy();
    expect(screen.getByText('Plant/T101/Level')).toBeTruthy();
    expect(screen.getByLabelText('Name')).toHaveValue('AcmeWater');
  });

  it('assigns checked signals to the node Asset without rewriting mqttTopic', async () => {
    getAssets.mockResolvedValue([
      { id: 42, path: 'AcmeWater/Site1/RawWater/Train1/V101', segment: 'V101', level: 'WORK_CELL' },
    ]);
    getSubscribedSignals.mockResolvedValue([
      {
        serverId: 's1',
        serverName: 'opcplc',
        nodeId: 'ns=3;s=T101',
        browsePath: 'T101/Level',
        displayName: 'Level',
        mqttTopic: 'Plant/T101/Level',
        subscribed: true,
      },
    ]);
    updateConnectivityTag.mockResolvedValue({
      serverId: 's1',
      nodeId: 'ns=3;s=T101',
      browsePath: 'T101/Level',
      displayName: 'Level',
      mqttTopic: 'Plant/T101/Level',
      subscribed: true,
      assetId: 42,
      assetPath: 'AcmeWater/Site1/RawWater/Train1/V101',
    });
    render(<HierarchyView />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Attach signals to Cell V101' })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Attach signals to Cell V101' }));
    fireEvent.click(screen.getByRole('checkbox', { name: /level/i }));
    fireEvent.click(screen.getByRole('button', { name: 'Attach' }));

    await waitFor(() =>
      expect(updateConnectivityTag).toHaveBeenCalledWith('s1', 'ns=3;s=T101', { assetId: 42 }),
    );
    expect(updateConnectivityTag.mock.calls[0][2]).not.toHaveProperty('mqttTopic');
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Cell V101' }).querySelector('[aria-label="Signals connected"]'),
      ).toBeTruthy(),
    );
  });

  it('clears the Asset when an assigned signal is unchecked', async () => {
    getAssets.mockResolvedValue([
      { id: 42, path: 'AcmeWater/Site1/RawWater/Train1/V101', segment: 'V101', level: 'WORK_CELL' },
    ]);
    getSubscribedSignals.mockResolvedValue([
      {
        serverId: 's1',
        serverName: 'opcplc',
        nodeId: 'ns=3;s=T101',
        browsePath: 'T101/Level',
        displayName: 'Level',
        mqttTopic: 'Plant/T101/Level',
        subscribed: true,
        assetId: 42,
        assetPath: 'AcmeWater/Site1/RawWater/Train1/V101',
      },
    ]);
    updateConnectivityTag.mockResolvedValue({
      serverId: 's1',
      nodeId: 'ns=3;s=T101',
      mqttTopic: 'Plant/T101/Level',
      displayName: 'Level',
      browsePath: 'T101/Level',
      subscribed: true,
      assetId: null,
      assetPath: null,
    });
    render(<HierarchyView />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Attach signals to Cell V101' })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Attach signals to Cell V101' }));
    expect(screen.getByRole('checkbox', { name: /level/i })).toBeChecked();
    fireEvent.click(screen.getByRole('checkbox', { name: /level/i }));
    fireEvent.click(screen.getByRole('button', { name: 'Attach' }));

    await waitFor(() =>
      expect(updateConnectivityTag).toHaveBeenCalledWith('s1', 'ns=3;s=T101', { assetId: null }),
    );
  });

  it('does not attach when the node is missing from the Asset Model', async () => {
    getSubscribedSignals.mockResolvedValue([
      {
        serverId: 's1',
        serverName: 'opcplc',
        nodeId: 'ns=3;s=T101',
        browsePath: 'T101/Level',
        displayName: 'Level',
        mqttTopic: 'Plant/T101/Level',
        subscribed: true,
      },
    ]);
    render(<HierarchyView />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Attach signals to Cell V101' })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Attach signals to Cell V101' }));
    expect(screen.getByText(/not in the asset model/i)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Attach' })).toBeDisabled();
    expect(updateConnectivityTag).not.toHaveBeenCalled();
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

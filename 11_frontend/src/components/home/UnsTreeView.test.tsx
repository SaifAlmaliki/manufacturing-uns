import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { UnsNode } from '../../types/uns';

const uns = vi.hoisted(() => ({
  rootNodes: [] as UnsNode[],
  expandedNodes: new Set<string>(),
  toggleNodeExpanded: vi.fn(),
  selectedNode: null as UnsNode | null,
  selectNode: vi.fn(),
  treeLoading: false,
  refreshTree: vi.fn(),
  settings: { staleThresholdMinutes: 5 },
  isBookmarked: () => false,
  addBookmark: vi.fn(),
  removeBookmark: vi.fn(),
}));
vi.mock('../../context/UNSContext', () => ({ useUNS: () => uns }));

import { UnsTreeView } from './UnsTreeView';

const site: UnsNode = {
  topic: 'HalabjaWTP/Halabja',
  name: 'Halabja',
  lastUpdated: '',
  isLeaf: false,
  nodeType: 'SITE',
  children: [
    {
      topic: 'HalabjaWTP/Halabja/Distribution',
      name: 'Distribution',
      lastUpdated: '',
      isLeaf: false,
      nodeType: 'AREA',
      children: [],
    },
  ],
};

const enterprise: UnsNode = {
  topic: 'HalabjaWTP',
  name: 'HalabjaWTP',
  lastUpdated: '',
  isLeaf: false,
  nodeType: 'ENTERPRISE',
  children: [site],
};

beforeEach(() => {
  uns.rootNodes = [enterprise];
  uns.expandedNodes = new Set(['HalabjaWTP', 'HalabjaWTP/Halabja']);
  uns.selectedNode = null;
});

describe('UnsTreeView connected-signal dots', () => {
  it('marks plant nodes that have a subscribed signal, and not siblings without one', () => {
    render(
      <UnsTreeView
        connectedTags={[
          {
            serverId: 's1',
            nodeId: 'n1',
            browsePath: 'Distribution/P201/Fault',
            displayName: 'Fault',
            mqttTopic: 'HalabjaWTP/Halabja/Distribution/P201/Fault',
            subscribed: true,
          },
        ]}
      />,
    );

    const distribution = screen.getByText('Distribution').closest('.group');
    const siteRow = screen.getByText('Halabja').closest('.group');
    expect(distribution?.querySelector('[aria-label="Signals connected"]')).toBeTruthy();
    expect(siteRow?.querySelector('[aria-label="Signals connected"]')).toBeTruthy();
    expect(screen.getByText('HalabjaWTP').closest('.group')?.querySelector('[aria-label="Signals connected"]')).toBeTruthy();
  });

  it('does not mark nodes when no signals are connected', () => {
    render(<UnsTreeView connectedTags={[]} />);
    expect(screen.queryByLabelText('Signals connected')).toBeNull();
  });
});

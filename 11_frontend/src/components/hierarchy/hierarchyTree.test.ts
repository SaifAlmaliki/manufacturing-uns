import { describe, expect, it } from 'vitest';
import type { GraphqlHierarchyTree } from '../../services/graphql/types';
import {
  ancestorKeys,
  childRefs,
  expandableKeys,
  assetIdForPrefix,
  insertDescendant,
  nodeKey,
  prefixHasConnectedSignal,
} from './hierarchyTree';

const TREE: GraphqlHierarchyTree = {
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

describe('insertDescendant', () => {
  it('creates a default Area and Line under a Site and returns the Line', () => {
    const result = insertDescendant(TREE, { level: 'site', site: 0 }, 'line');
    expect(result).not.toBeNull();
    expect(result?.child).toEqual({ level: 'line', site: 0, area: 1, line: 0 });
    expect(result?.tree.sites[0].areas[1]).toEqual({
      name: 'Area',
      kind: 'production',
      lines: [{ name: 'Line', cells: [] }],
    });
  });

  it('creates a default Cell and Machine under a Line and returns the Machine', () => {
    const result = insertDescendant(
      TREE,
      { level: 'line', site: 0, area: 0, line: 0 },
      'machine',
    );
    expect(result?.child).toEqual({
      level: 'machine',
      site: 0,
      area: 0,
      line: 0,
      cell: 1,
      machine: 0,
    });
    expect(result?.tree.sites[0].areas[0].lines[0].cells[1]).toEqual({
      name: 'Cell',
      machines: ['Machine'],
    });
    expect(result?.tree.sites[0].areas[0].lines[0].cells[0].name).toBe('V101');
  });

  it('adds only a Machine under a Cell', () => {
    const result = insertDescendant(
      TREE,
      { level: 'cell', site: 0, area: 0, line: 0, cell: 0 },
      'machine',
    );
    expect(result?.tree.sites[0].areas[0].lines[0].cells[0].machines).toEqual(['Machine']);
    expect(result?.child).toEqual({
      level: 'machine',
      site: 0,
      area: 0,
      line: 0,
      cell: 0,
      machine: 0,
    });
  });

  it('returns null when the parent is a Machine', () => {
    expect(
      insertDescendant(
        TREE,
        { level: 'machine', site: 0, area: 0, line: 0, cell: 0, machine: 0 },
        'cell',
      ),
    ).toBeNull();
  });
});

describe('collapse keys', () => {
  it('names each node so expand state survives a rename', () => {
    expect(nodeKey({ level: 'enterprise' })).toBe('enterprise');
    expect(nodeKey({ level: 'site', site: 0 })).toBe('site:0');
    expect(nodeKey({ level: 'cell', site: 0, area: 0, line: 0, cell: 0 })).toBe('cell:0:0:0:0');
  });

  it('lists only the direct children of a node', () => {
    expect(childRefs(TREE, { level: 'enterprise' })).toEqual([{ level: 'site', site: 0 }]);
    expect(childRefs(TREE, { level: 'line', site: 0, area: 0, line: 0 })).toEqual([
      { level: 'cell', site: 0, area: 0, line: 0, cell: 0 },
    ]);
    expect(childRefs(TREE, { level: 'cell', site: 0, area: 0, line: 0, cell: 0 })).toEqual([]);
  });

  it('starts every parent with children expanded', () => {
    expect(expandableKeys(TREE)).toEqual([
      'enterprise',
      'site:0',
      'area:0:0',
      'line:0:0:0',
    ]);
  });

  it('returns the ancestors that must stay open to show a child', () => {
    expect(ancestorKeys({ level: 'cell', site: 0, area: 0, line: 0, cell: 0 })).toEqual([
      'line:0:0:0',
      'area:0:0',
      'site:0',
      'enterprise',
    ]);
    expect(ancestorKeys({ level: 'enterprise' })).toEqual([]);
  });
});

describe('prefixHasConnectedSignal', () => {
  const signals = [
    { mqttTopic: 'AcmeWater/Site1/RawWater/Train1/V101/Level', assetPath: null },
    {
      mqttTopic: 'Server/OpcPlc/Pressure',
      assetPath: 'AcmeWater/Site1/RawWater',
    },
  ];

  it('marks a node connected when a subscribed signal lives under its prefix', () => {
    expect(prefixHasConnectedSignal('AcmeWater/Site1/RawWater/Train1/V101', signals)).toBe(true);
    expect(prefixHasConnectedSignal('AcmeWater/Site1', signals)).toBe(true);
    expect(prefixHasConnectedSignal('AcmeWater', signals)).toBe(true);
  });

  it('marks a node connected when its Asset path is assigned to a signal', () => {
    expect(prefixHasConnectedSignal('AcmeWater/Site1/RawWater', signals)).toBe(true);
  });

  it('does not mark a sibling branch that has no signals', () => {
    expect(prefixHasConnectedSignal('AcmeWater/Site2', signals)).toBe(false);
    expect(prefixHasConnectedSignal('AcmeWater/Site1/Treatment', signals)).toBe(false);
  });
});

describe('assetIdForPrefix', () => {
  const assets = [
    { id: 7, path: 'AcmeWater/Site1' },
    { id: 42, path: 'AcmeWater/Site1/RawWater/Train1/V101' },
  ];

  it('returns the Asset Model id for an exact plant-tree prefix', () => {
    expect(assetIdForPrefix(assets, 'AcmeWater/Site1/RawWater/Train1/V101')).toBe(42);
    expect(assetIdForPrefix(assets, 'AcmeWater/Site1')).toBe(7);
  });

  it('returns null when the node is not in the Asset Model', () => {
    expect(assetIdForPrefix(assets, 'AcmeWater/Site1/Treatment')).toBeNull();
  });
});

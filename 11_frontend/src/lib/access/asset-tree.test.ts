import { describe, expect, it } from 'vitest';
import { expandableAssetPaths, nestAssets, parseAssetLevel } from './asset-tree';

const ASSETS = [
  { id: 1, path: 'AcmeWater', segment: 'AcmeWater', level: 'ENTERPRISE' },
  { id: 2, path: 'AcmeWater/Site1', segment: 'Site1', level: 'SITE' },
  { id: 9, path: 'AcmeWater/Site1/Filtration', segment: 'Filtration', level: 'AREA' },
];

describe('nestAssets', () => {
  it('nests getAssets rows by path so the picker can reuse a collapsible tree', () => {
    const roots = nestAssets(ASSETS);
    expect(roots).toHaveLength(1);
    expect(roots[0].path).toBe('AcmeWater');
    expect(roots[0].children.map((child) => child.path)).toEqual(['AcmeWater/Site1']);
    expect(roots[0].children[0].children.map((child) => child.path)).toEqual([
      'AcmeWater/Site1/Filtration',
    ]);
  });

  it('lists every parent path as expandable', () => {
    expect(expandableAssetPaths(nestAssets(ASSETS))).toEqual([
      'AcmeWater',
      'AcmeWater/Site1',
    ]);
  });
});

describe('parseAssetLevel', () => {
  it('maps Asset Model levels onto the hierarchy tree icons', () => {
    expect(parseAssetLevel('ENTERPRISE')).toBe('enterprise');
    expect(parseAssetLevel('WORK_CELL')).toBe('cell');
    expect(parseAssetLevel('machine')).toBe('machine');
  });
});

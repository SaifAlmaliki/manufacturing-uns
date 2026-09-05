import { describe, expect, it } from 'vitest';
import {
  EDITOR_LEVELS,
  LEAF_TITLE,
  addDescription,
  levelDef,
  remainingChildren,
} from './hierarchyLevels';

describe('remainingChildren', () => {
  it('lists every editor level below Area', () => {
    expect(remainingChildren('area')).toEqual(['line', 'cell', 'machine']);
  });

  it('lists Site through Machine under Enterprise', () => {
    expect(remainingChildren('enterprise')).toEqual([
      'site',
      'area',
      'line',
      'cell',
      'machine',
    ]);
  });

  it('lists Machine under Cell', () => {
    expect(remainingChildren('cell')).toEqual(['machine']);
  });

  it('lists nothing under Machine', () => {
    expect(remainingChildren('machine')).toEqual([]);
  });
});

describe('addDescription', () => {
  it('describes an adjacent Area under a Site', () => {
    expect(addDescription('site', 'area')).toBe(
      'Area — a production area within this site.',
    );
  });

  it('describes a skipped Line under a Site', () => {
    expect(addDescription('site', 'line')).toBe(
      'Line — a production line (an Area will be created to hold it).',
    );
  });

  it('describes a Machine under a Cell', () => {
    expect(addDescription('cell', 'machine')).toBe(
      'Machine — equipment under this cell. After Save it is a MACHINE Asset the rest of the platform can attach tags to.',
    );
  });

  it('describes a skipped Machine under a Line', () => {
    expect(addDescription('line', 'machine')).toBe(
      'Machine — equipment (a Cell will be created to hold it).',
    );
  });
});

describe('catalog', () => {
  it('names the six editor levels and the leaf title', () => {
    expect(EDITOR_LEVELS.map((l) => l.id)).toEqual([
      'enterprise',
      'site',
      'area',
      'line',
      'cell',
      'machine',
    ]);
    expect(levelDef('machine').label).toBe('Machine');
    expect(levelDef('machine').defaultName).toBe('Machine');
    expect(LEAF_TITLE).toBe('Machine is a leaf — nothing can be added under it.');
  });
});

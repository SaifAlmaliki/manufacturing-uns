import { describe, expect, it } from 'vitest';
import type { GraphqlSubscribedSignal } from '../../services/graphql/types';
import {
  mergeSignalDraft,
  stageSignalPatch,
  withAddedLabel,
} from './signal-drafts';

const ROW: GraphqlSubscribedSignal = {
  serverId: 's1',
  serverName: 'opcplc',
  nodeId: 'ns=3;s=T101',
  browsePath: 'T101/Level',
  displayName: 'Level',
  mqttTopic: 'Plant/T101/Level',
  subscribed: true,
  unitOfMeasure: null,
  labels: [],
};

describe('signal drafts', () => {
  it('merges a staged patch onto the catalog row for display', () => {
    expect(
      mergeSignalDraft(ROW, { unitOfMeasure: '°C', assetId: 9 }),
    ).toMatchObject({
      ...ROW,
      unitOfMeasure: '°C',
      assetId: 9,
    });
  });

  it('stages a patch without dropping earlier fields on the same row', () => {
    const once = stageSignalPatch({}, 'k', ROW, { unitOfMeasure: '°C' });
    const twice = stageSignalPatch(once, 'k', ROW, { assetId: 9 });
    expect(twice.k).toEqual({ unitOfMeasure: '°C', assetId: 9 });
  });

  it('drops a draft when the staged value matches the catalog row', () => {
    const dirty = stageSignalPatch({}, 'k', ROW, { unitOfMeasure: '°C' });
    const clean = stageSignalPatch(dirty, 'k', ROW, { unitOfMeasure: null });
    expect(clean.k).toBeUndefined();
  });

  it('appends a label onto the displayed labels, not replacing them', () => {
    const row = { ...ROW, labels: ['Cycle'] };
    expect(withAddedLabel(row, undefined, 'Custom')).toEqual({
      labels: ['Cycle', 'Custom'],
    });
    expect(withAddedLabel(row, { labels: ['Cycle', 'Hold'] }, 'Custom')).toEqual({
      labels: ['Cycle', 'Hold', 'Custom'],
    });
  });
});

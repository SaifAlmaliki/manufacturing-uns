import { describe, expect, it } from 'vitest';
import { contextChip, pageContext } from './copilotContext';

describe('pageContext', () => {
  it('sets alarmTopic from alerts selection', () => {
    const ctx = pageContext({
      pathname: '/alerts/active',
      selectedAlarmTopic: 'Acme/L1',
    });
    expect(ctx.alarmTopic).toBe('Acme/L1');
    expect(ctx.route).toBe('/alerts/active');
  });

  it('leaves paths empty when nothing is selected', () => {
    const ctx = pageContext({ pathname: '/dashboard' });
    expect(ctx.assetPath).toBe('');
    expect(ctx.metricKey).toBe('');
    expect(ctx.alarmTopic).toBe('');
  });

  it('uses selectedTopic when it looks like a path', () => {
    const ctx = pageContext({
      pathname: '/condition-monitoring',
      selectedTopic: 'Halabja/RawWater/Train10/P101',
    });
    expect(ctx.assetPath).toBe('Halabja/RawWater/Train10/P101');
  });
});

describe('contextChip', () => {
  it('shows the my Access Groups placeholder before scope loads', () => {
    expect(
      contextChip({
        route: '/dashboard',
        assetPath: '',
        metricKey: '',
        alarmTopic: '',
      }),
    ).toBe('Plant · my Access Groups');
  });

  it('names Access Group roots when nothing is selected', () => {
    expect(
      contextChip(
        { route: '/dashboard', assetPath: '', metricKey: '', alarmTopic: '' },
        { roots: ['AcmeWater/Site1'], unrestricted: false },
      ),
    ).toBe('Plant · AcmeWater/Site1');
  });

  it('counts Access Groups when there are several roots', () => {
    expect(
      contextChip(
        { route: '/dashboard', assetPath: '', metricKey: '', alarmTopic: '' },
        { roots: ['Acme/Site1', 'Acme/Site2'], unrestricted: false },
      ),
    ).toBe('Plant · 2 Access Groups');
  });

  it('does not say no Asset selected', () => {
    expect(
      contextChip({ route: '/dashboard', assetPath: '', metricKey: '', alarmTopic: '' }),
    ).not.toMatch(/no Asset selected/i);
  });

  it('prefers assetPath', () => {
    expect(
      contextChip({
        route: '/condition-monitoring',
        assetPath: 'Halabja/RawWater/Train10/P101',
        metricKey: 'flow',
        alarmTopic: '',
      }),
    ).toBe('Halabja/RawWater/Train10/P101');
  });
});

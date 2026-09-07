import { describe, expect, it } from 'vitest';
import { citationTarget } from './citationJump';

describe('citationTarget', () => {
  it('routes historian citations to historian', () => {
    expect(citationTarget('historian')).toBe('#/historian');
  });

  it('routes alarm citations to alerts', () => {
    expect(citationTarget('alarms')).toBe('#/alerts/active');
  });

  it('routes live and model citations to condition monitoring', () => {
    expect(citationTarget('live')).toBe('#/condition-monitoring');
    expect(citationTarget('model')).toBe('#/condition-monitoring');
  });
});

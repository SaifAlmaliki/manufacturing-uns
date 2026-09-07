import type { CopilotSource } from './copilotContext';

export function citationTarget(
  source: CopilotSource,
): '#/historian' | '#/alerts/active' | '#/condition-monitoring' {
  if (source === 'historian') return '#/historian';
  if (source === 'alarms') return '#/alerts/active';
  return '#/condition-monitoring';
}

export type CopilotSource = 'model' | 'historian' | 'live' | 'alarms';

export type PageContext = {
  route: string;
  assetPath: string;
  metricKey: string;
  alarmTopic: string;
};

export function pageContext(input: {
  pathname: string;
  selectedTopic?: string;
  selectedMetricKey?: string;
  selectedAlarmTopic?: string;
}): PageContext {
  const assetPath =
    input.selectedTopic && input.selectedTopic.includes('/')
      ? input.selectedTopic
      : '';
  return {
    route: input.pathname,
    assetPath,
    metricKey: input.selectedMetricKey ?? '',
    alarmTopic: input.selectedAlarmTopic ?? '',
  };
}

export function contextChip(ctx: PageContext): string {
  const focus = ctx.assetPath || ctx.metricKey || ctx.alarmTopic;
  return focus ? focus : 'Plant · no Asset selected';
}

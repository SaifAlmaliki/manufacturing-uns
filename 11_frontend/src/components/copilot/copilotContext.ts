export type CopilotSource = 'model' | 'historian' | 'live' | 'alarms';

export type CopilotScope = { roots: string[]; unrestricted: boolean };

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

export function contextChip(ctx: PageContext, scope?: CopilotScope | null): string {
  const focus = ctx.assetPath || ctx.metricKey || ctx.alarmTopic;
  if (focus) return focus;
  const roots = scope?.roots ?? [];
  if (roots.length === 1) return `Plant · ${roots[0]}`;
  if (roots.length > 1) return `Plant · ${roots.length} Access Groups`;
  return 'Plant · my Access Groups';
}

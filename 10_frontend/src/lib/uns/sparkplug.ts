export const SPARKPLUG_PREFIX = 'spBv1.0/'

export function isSparkplugTopic(topic: string): boolean {
  return topic.startsWith(SPARKPLUG_PREFIX)
}

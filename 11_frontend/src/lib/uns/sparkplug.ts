export const SPARKPLUG_PREFIX = 'spBv1.0/'

export function isSparkplugTopic(topic: string): boolean {
  return topic.startsWith(SPARKPLUG_PREFIX)
}

export function parseSparkplugTopic(topic: string): {
  groupId: string
  edgeNodeId: string
  deviceId?: string
} {
  const parts = topic.replace(SPARKPLUG_PREFIX, '').split('/')
  return {
    groupId: parts[0] ?? '',
    edgeNodeId: parts[2] ?? parts[1] ?? '',
    deviceId: parts[3],
  }
}

export function parentNamespace(namespace: string): string {
  const i = namespace.lastIndexOf('/')
  return i === -1 ? '' : namespace.slice(0, i)
}

export function childrenTopic(namespace: string): string {
  return namespace === '' ? '+' : `${namespace}/+`
}

export function historianTopic(namespace: string): string {
  return `${namespace}/#`
}

export function mqttTopicInput(topic: string): { topic: string } {
  return { topic }
}

export function mqttTopicInputs(topics: string[]): { topic: string }[] {
  return topics.map(mqttTopicInput)
}

/** Number of ISA-95 segments in a namespace topic (e.g. CovestroAG/Krefeld/.../G1 → 6). */
export function topicDepth(topic: string): number {
  return topic.split('/').filter(Boolean).length
}

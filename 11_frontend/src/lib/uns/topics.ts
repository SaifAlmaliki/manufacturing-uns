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

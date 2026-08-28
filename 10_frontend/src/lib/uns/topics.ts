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

export function isFeedHighlight(topic: string, selected: string | null): boolean {
  if (!selected) {
    return false
  }
  return topic === selected || topic.startsWith(`${selected}/`)
}

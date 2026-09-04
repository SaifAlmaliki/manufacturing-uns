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

/** Number of ISA-95 segments in a namespace topic (e.g. Enterprise/Site/Area/Line/Cell/Eq → 6). */
export function topicDepth(topic: string): number {
  return topic.split('/').filter(Boolean).length
}

/**
 * Split a topic into segments, preserving empty ones.
 *
 * MQTT permits empty levels (`a//c`), so they are kept rather than discarded —
 * mirrors `uns_model.topic_path.split_topic`.
 */
export function splitTopic(topic: string): string[] {
  if (topic === '') {
    return []
  }
  return topic.split('/')
}

/**
 * Join non-empty segments with the topic separator — mirrors `uns_model.topic_path.join_segments`.
 * Empty segments are dropped so a missing level does not introduce a stray slash.
 */
export function joinSegments(...segments: string[]): string {
  return segments.filter((segment) => segment !== '').join('/')
}

/**
 * Return `name` if it is a legal single topic segment.
 *
 * Rejects empty names and names containing the separator, since either would
 * corrupt segment boundaries when joined into a topic — mirrors
 * `uns_model.topic_path.validate_segment`.
 */
export function validateSegment(name: string): string {
  if (name === '') {
    throw new Error(`segment must be non-empty: ${name}`)
  }
  if (name.includes('/')) {
    throw new Error(`segment must not contain '/': ${name}`)
  }
  return name
}

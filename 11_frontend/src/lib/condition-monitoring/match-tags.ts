import type { GraphqlConnectivityTag } from '../../services/graphql/types';
import type { UnsNode } from '../../types/uns';

export function pathSegments(topic: string): string[] {
  return topic.split('/').filter(Boolean);
}

export function tagMatchesNode(tag: GraphqlConnectivityTag, node: UnsNode): boolean {
  const topic = tag.mqttTopic;
  if (topic === node.topic || topic.startsWith(`${node.topic}/`)) return true;
  const assetPath = tag.assetPath;
  if (assetPath) {
    if (
      assetPath === node.topic
      || assetPath.startsWith(`${node.topic}/`)
      || node.topic.startsWith(`${assetPath}/`)
    ) {
      return true;
    }
    const assetLeaf = pathSegments(assetPath).at(-1);
    const nodeLeaf = pathSegments(node.topic).at(-1);
    if (assetLeaf && assetLeaf === nodeLeaf) return true;
  }
  const leaf = pathSegments(node.topic).at(-1);
  if (!leaf) return false;
  const haystack = [...pathSegments(tag.mqttTopic), ...pathSegments(tag.browsePath)];
  return haystack.includes(leaf);
}

export function collectLoadedDescendants(node: UnsNode): UnsNode[] {
  const out: UnsNode[] = [node];
  for (const child of node.children ?? []) {
    out.push(...collectLoadedDescendants(child));
  }
  return out;
}

export function tagInScope(tag: GraphqlConnectivityTag, scope: UnsNode | null): boolean {
  if (scope === null) return true;
  return collectLoadedDescendants(scope).some((node) => tagMatchesNode(tag, node));
}

export function filterTagsBySearch(
  tags: GraphqlConnectivityTag[],
  search: string,
): GraphqlConnectivityTag[] {
  const q = search.trim().toLowerCase();
  if (!q) return tags;
  return tags.filter(
    (tag) =>
      tag.displayName.toLowerCase().includes(q) || tag.mqttTopic.toLowerCase().includes(q),
  );
}

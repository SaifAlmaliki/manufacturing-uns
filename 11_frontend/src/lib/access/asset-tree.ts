import type { AccessAssetDto } from '../../services/graphql/types';
import { EDITOR_LEVELS, type NodeLevel } from '../../components/hierarchy/hierarchyLevels';

export type AssetTreeNode = AccessAssetDto & { children: AssetTreeNode[] };

export function nestAssets(assets: AccessAssetDto[]): AssetTreeNode[] {
  const sorted = [...assets].sort((a, b) => a.path.localeCompare(b.path));
  const byPath = new Map<string, AssetTreeNode>();
  for (const asset of sorted) {
    byPath.set(asset.path, { ...asset, children: [] });
  }
  const roots: AssetTreeNode[] = [];
  for (const asset of sorted) {
    const node = byPath.get(asset.path);
    if (!node) {
      continue;
    }
    const slash = asset.path.lastIndexOf('/');
    const parentPath = slash === -1 ? '' : asset.path.slice(0, slash);
    const parent = parentPath ? byPath.get(parentPath) : undefined;
    if (parent) {
      parent.children.push(node);
    } else {
      roots.push(node);
    }
  }
  return roots;
}

export function expandableAssetPaths(nodes: AssetTreeNode[]): string[] {
  const out: string[] = [];
  const walk = (node: AssetTreeNode) => {
    if (node.children.length > 0) {
      out.push(node.path);
      node.children.forEach(walk);
    }
  };
  nodes.forEach(walk);
  return out;
}

export function parseAssetLevel(level: string): NodeLevel | null {
  const key = level.toLowerCase().replace(/work_?cell/, 'cell');
  return EDITOR_LEVELS.some((row) => row.id === key) ? (key as NodeLevel) : null;
}

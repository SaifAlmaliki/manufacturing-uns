import { levelDef, type NodeLevel } from './hierarchyLevels';

export function AssetLevelIcon({
  level,
  className = 'size-3.5 shrink-0',
}: {
  level: NodeLevel;
  className?: string;
}) {
  const Icon = levelDef(level).icon;
  return <Icon className={className} aria-hidden="true" />;
}

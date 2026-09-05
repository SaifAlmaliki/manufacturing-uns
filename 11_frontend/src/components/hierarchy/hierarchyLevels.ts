import { Cog, Cpu, Factory, GitBranch, Globe, MapPinned, type LucideIcon } from 'lucide-react';

export type NodeLevel = 'enterprise' | 'site' | 'area' | 'line' | 'cell' | 'machine';

export type LevelDef = {
  id: NodeLevel;
  label: string;
  defaultName: string | null;
  icon: LucideIcon;
};

export const EDITOR_LEVELS: LevelDef[] = [
  { id: 'enterprise', label: 'Enterprise', defaultName: null, icon: Globe },
  { id: 'site', label: 'Site', defaultName: 'Site', icon: Factory },
  { id: 'area', label: 'Area', defaultName: 'Area', icon: MapPinned },
  { id: 'line', label: 'Line', defaultName: 'Line', icon: GitBranch },
  { id: 'cell', label: 'Cell', defaultName: 'Cell', icon: Cpu },
  { id: 'machine', label: 'Machine', defaultName: 'Machine', icon: Cog },
];

export const LEAF_TITLE = 'Machine is a leaf — nothing can be added under it.';

const ORDER: NodeLevel[] = EDITOR_LEVELS.map((row) => row.id);

export function levelDef(id: NodeLevel): LevelDef {
  const found = EDITOR_LEVELS.find((row) => row.id === id);
  if (!found) {
    throw new Error(`Unknown editor level: ${id}`);
  }
  return found;
}

export function remainingChildren(parent: NodeLevel): NodeLevel[] {
  return ORDER.slice(ORDER.indexOf(parent) + 1);
}

const DESCRIPTIONS: Record<string, string> = {
  'enterprise:site': 'Site — a physical plant or facility under this enterprise.',
  'enterprise:area': 'Area — a production area (a Site will be created to hold it).',
  'enterprise:line': 'Line — a production line (a Site and Area will be created to hold it).',
  'enterprise:cell': 'Cell — an instance tag (a Site, Area, and Line will be created to hold it).',
  'enterprise:machine':
    'Machine — equipment (a Site, Area, Line, and Cell will be created to hold it).',
  'site:area': 'Area — a production area within this site.',
  'site:line': 'Line — a production line (an Area will be created to hold it).',
  'site:cell': 'Cell — an instance tag (an Area and Line will be created to hold it).',
  'site:machine': 'Machine — equipment (an Area, Line, and Cell will be created to hold it).',
  'area:line': 'Line — a production line under this area.',
  'area:cell': 'Cell — an instance tag (a Line will be created to hold it).',
  'area:machine': 'Machine — equipment (a Line and Cell will be created to hold it).',
  'line:cell': 'Cell — an instance tag under this line.',
  'line:machine': 'Machine — equipment (a Cell will be created to hold it).',
  'cell:machine':
    'Machine — equipment under this cell. After Save it is a MACHINE Asset the rest of the platform can attach tags to.',
};

export function addDescription(parent: NodeLevel, target: NodeLevel): string {
  return DESCRIPTIONS[`${parent}:${target}`] ?? '';
}

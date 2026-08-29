/**
 * Role-Based Access Control (RBAC) & User Management Types
 */

export type UserRole = 'admin' | 'engineer' | 'operator' | 'auditor' | 'viewer';

export type FeatureKey =
  | 'uns_tree'
  | 'historian'
  | 'sparkplug'
  | 'streams'
  | 'alarms'
  | 'system_ops'
  | 'user_management'
  | 'export_csv'
  | 'settings_edit'
  | 'payload_publish'
  | 'topic_bookmarks';

export interface FeatureDefinition {
  key: FeatureKey;
  label: string;
  description: string;
  category: 'Core Navigation' | 'Data & Export' | 'System & Admin';
  adminOnly?: boolean;
}

export const SYSTEM_FEATURES: FeatureDefinition[] = [
  {
    key: 'uns_tree',
    label: 'UNS Tree Hierarchy',
    description: 'Browse, search, and inspect the ISA-95 node tree and live MQTT payload',
    category: 'Core Navigation',
  },
  {
    key: 'alarms',
    label: 'Alarms & Alert Rules',
    description: 'Configure real-time threshold triggers, role-based alerts, and active plant incident acknowledgements',
    category: 'Core Navigation',
  },
  {
    key: 'historian',
    label: 'Timescale Historian',
    description: 'Query and visualize time-series telemetry events, time ranges, and filters',
    category: 'Core Navigation',
  },
  {
    key: 'sparkplug',
    label: 'Sparkplug B Decoder',
    description: 'View Edge Node health, birth/death certificates, and decoded metric metrics',
    category: 'Core Navigation',
  },
  {
    key: 'streams',
    label: 'Kafka Streams Monitor',
    description: 'Live real-time stream subscription to Kafka topics with ring-buffer inspector',
    category: 'Core Navigation',
  },
  {
    key: 'system_ops',
    label: 'System Health & Ops',
    description: 'View GraphQL 07_uns_graphql connectivity, subsystem status, and schema matrix',
    category: 'Core Navigation',
  },
  {
    key: 'user_management',
    label: 'User Management & RBAC',
    description: 'Administer system users, assign roles, and grant/revoke granular feature access',
    category: 'System & Admin',
    adminOnly: true,
  },
  {
    key: 'export_csv',
    label: 'CSV Data Export',
    description: 'Export historian telemetry datasets and message logs to downloadable CSV',
    category: 'Data & Export',
  },
  {
    key: 'payload_publish',
    label: 'MQTT Payload Publish',
    description: 'Publish simulated control telemetry or override node payload states',
    category: 'Data & Export',
  },
  {
    key: 'settings_edit',
    label: 'Console Configuration',
    description: 'Modify GraphQL HTTP/WS endpoint URLs and branding parameters',
    category: 'System & Admin',
  },
  {
    key: 'topic_bookmarks',
    label: 'Manage Topic Bookmarks',
    description: 'Save, edit, and organize persistent topic shortcuts and aliases',
    category: 'Data & Export',
  },
];

export interface RoleConfig {
  role: UserRole;
  label: string;
  badgeBg: string;
  badgeText: string;
  badgeBorder: string;
  description: string;
  defaultPermissions: Record<FeatureKey, boolean>;
}

export const ROLE_CONFIGS: Record<UserRole, RoleConfig> = {
  admin: {
    role: 'admin',
    label: 'System Admin',
    badgeBg: 'bg-rose-50 dark:bg-rose-500/10',
    badgeText: 'text-rose-700 dark:text-rose-400',
    badgeBorder: 'border-rose-200 dark:border-rose-500/30',
    description: 'Full unrestricted superuser access. Can manage users, grant feature permissions, and reconfigure system.',
    defaultPermissions: {
      uns_tree: true,
      alarms: true,
      historian: true,
      sparkplug: true,
      streams: true,
      system_ops: true,
      user_management: true,
      export_csv: true,
      settings_edit: true,
      payload_publish: true,
      topic_bookmarks: true,
    },
  },
  engineer: {
    role: 'engineer',
    label: 'Plant Engineer',
    badgeBg: 'bg-amber-50 dark:bg-[#FFC107]/10',
    badgeText: 'text-amber-700 dark:text-[#FFC107]',
    badgeBorder: 'border-amber-200 dark:border-[#FFC107]/30',
    description: 'Full engineering access to telemetry, historian, Sparkplug B, Kafka streams, alarms, and CSV export.',
    defaultPermissions: {
      uns_tree: true,
      alarms: true,
      historian: true,
      sparkplug: true,
      streams: true,
      system_ops: true,
      user_management: false,
      export_csv: true,
      settings_edit: false,
      payload_publish: true,
      topic_bookmarks: true,
    },
  },
  operator: {
    role: 'operator',
    label: 'Control Room Operator',
    badgeBg: 'bg-emerald-50 dark:bg-emerald-500/10',
    badgeText: 'text-emerald-700 dark:text-emerald-400',
    badgeBorder: 'border-emerald-200 dark:border-emerald-500/30',
    description: 'Operational view of UNS tree, active alarms, Sparkplug B metrics, and bookmarked telemetry.',
    defaultPermissions: {
      uns_tree: true,
      alarms: true,
      historian: false,
      sparkplug: true,
      streams: false,
      system_ops: false,
      user_management: false,
      export_csv: false,
      settings_edit: false,
      payload_publish: false,
      topic_bookmarks: true,
    },
  },
  auditor: {
    role: 'auditor',
    label: 'Compliance Auditor',
    badgeBg: 'bg-purple-50 dark:bg-purple-500/10',
    badgeText: 'text-purple-700 dark:text-purple-400',
    badgeBorder: 'border-purple-200 dark:border-purple-500/30',
    description: 'Read-only access to historical event queries, alarm audit logs, Kafka event logs, and CSV exports.',
    defaultPermissions: {
      uns_tree: true,
      alarms: true,
      historian: true,
      sparkplug: false,
      streams: true,
      system_ops: false,
      user_management: false,
      export_csv: true,
      settings_edit: false,
      payload_publish: false,
      topic_bookmarks: true,
    },
  },
  viewer: {
    role: 'viewer',
    label: 'Read-Only Viewer',
    badgeBg: 'bg-slate-100 dark:bg-slate-500/10',
    badgeText: 'text-slate-700 dark:text-slate-400',
    badgeBorder: 'border-slate-300 dark:border-slate-500/30',
    description: 'Basic view-only access to public UNS tree hierarchy.',
    defaultPermissions: {
      uns_tree: true,
      alarms: false,
      historian: false,
      sparkplug: false,
      streams: false,
      system_ops: false,
      user_management: false,
      export_csv: false,
      settings_edit: false,
      payload_publish: false,
      topic_bookmarks: false,
    },
  },
};

export interface UserAccount {
  id: string;
  name: string;
  email: string;
  role: UserRole;
  department: string;
  plantLocation: string;
  avatarColor?: string;
  status: 'active' | 'suspended' | 'pending';
  createdAt: string;
  lastLogin: string;
  customPermissions: Record<FeatureKey, boolean>;
  notes?: string;
}

export interface AuditLogEntry {
  id: string;
  timestamp: string;
  actorEmail: string;
  targetUserEmail: string;
  action: 'CREATE_USER' | 'UPDATE_ROLE' | 'UPDATE_PERMISSIONS' | 'DELETE_USER' | 'TOGGLE_STATUS';
  details: string;
}

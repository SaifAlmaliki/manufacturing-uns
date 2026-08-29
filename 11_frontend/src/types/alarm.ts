import { UserRole } from './rbac';

export type AlarmSeverity = 'CRITICAL' | 'HIGH' | 'WARNING' | 'INFO';

export type AlarmCategory =
  | 'TEMPERATURE'
  | 'PRESSURE'
  | 'VIBRATION'
  | 'FLOW_RATE'
  | 'STALE_TIMEOUT'
  | 'NODE_OFFLINE'
  | 'COMMUNICATION'
  | 'THRESHOLD'
  | 'SAFETY'
  | 'CUSTOM';

export type AlarmConditionType =
  | 'GREATER_THAN'
  | 'LESS_THAN'
  | 'EQUALS'
  | 'NOT_EQUALS'
  | 'RANGE_OUTSIDE'
  | 'STALE_TIMEOUT'
  | 'CONTAINS';

export type AlarmStatus =
  | 'ACTIVE_UNACK'
  | 'ACTIVE_ACK'
  | 'CLEARED_UNACK'
  | 'RESOLVED';

export interface AlertRuleAction {
  inAppNotification: boolean;
  audioChime: boolean;
  mqttPublishOnTrigger: boolean;
  mqttAlarmTopic?: string;
  emailWebhook: boolean;
  webhookUrl?: string;
}

export interface AlertRule {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  severity: AlarmSeverity;
  category: AlarmCategory;
  topic: string; // Target ISA-95 or Sparkplug topic, or '*' for global
  metricField: string; // e.g. "temperature", "pressure", "status", "vibration_rms"
  condition: AlarmConditionType;
  thresholdValue: number | string | boolean;
  thresholdUpperValue?: number; // for RANGE_OUTSIDE
  unit?: string; // e.g. "°C", "bar", "mm/s", "min", "%"
  delaySeconds?: number; // debounce / time before triggering
  
  // ROLE-BASED TARGETING & ESCALATION (User requested: configure triggers based on pre-defined roles)
  targetRoles: UserRole[]; // e.g. ['operator', 'engineer', 'admin']
  escalationRole?: UserRole; // e.g. escalate to 'admin'
  escalationTimeoutMinutes?: number; // e.g. escalate if unack for 5 min
  autoResolveOnNormal: boolean;

  actions: AlertRuleAction;

  // Runtime / telemetry tracking
  triggerCount: number;
  lastTriggeredAt?: string;
  lastEvaluatedAt?: string;
  createdAt: string;
  updatedAt: string;
}

export interface ActiveAlarm {
  id: string;
  ruleId: string;
  ruleName: string;
  topic: string;
  severity: AlarmSeverity;
  category: AlarmCategory;
  conditionDescription: string;
  currentValue: unknown;
  unit?: string;
  status: AlarmStatus;
  triggeredAt: string;
  acknowledgedAt?: string;
  acknowledgedBy?: string;
  notes?: string;
  targetRoles: UserRole[];
  escalated?: boolean;
  clearedAt?: string;
}

export interface AlarmAuditEntry {
  id: string;
  timestamp: string;
  alarmId: string;
  ruleName: string;
  topic: string;
  severity: AlarmSeverity;
  action: 'TRIGGERED' | 'ACKNOWLEDGED' | 'RESOLVED' | 'ESCALATED' | 'SILENCED' | 'CLEARED' | 'RULE_UPDATED';
  actorName: string;
  actorRole: UserRole;
  details: string;
}

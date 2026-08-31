/**
 * Translation between an Alert Rule as the server stores it and as this console
 * renders it.
 *
 * Two differences worth naming, because both bite silently:
 *  - the console nests the notification settings under `actions`, the server keeps
 *    them flat, since a rule has one set of them and a nested column buys nothing;
 *  - `targetRoles` here is `notifyRoles` there — "roles" on a rule reads as "roles
 *    that may edit it" — and GraphQL spells the enum members in upper case.
 */

import type {
  AlarmCategory,
  AlarmConditionType,
  AlarmSeverity,
  AlertRule,
} from '../../types/alarm'
import type { UserRole } from '../../types/rbac'
import type { GraphqlAlertRule } from '../../services/graphql/types'

const SEVERITIES = new Set<string>(['CRITICAL', 'HIGH', 'WARNING', 'INFO'])

const CATEGORIES = new Set<string>([
  'TEMPERATURE',
  'PRESSURE',
  'VIBRATION',
  'FLOW_RATE',
  'STALE_TIMEOUT',
  'NODE_OFFLINE',
  'COMMUNICATION',
  'THRESHOLD',
  'SAFETY',
  'CUSTOM',
])

const CONDITIONS = new Set<string>([
  'GREATER_THAN',
  'LESS_THAN',
  'EQUALS',
  'NOT_EQUALS',
  'RANGE_OUTSIDE',
  'STALE_TIMEOUT',
  'CONTAINS',
])

const ROLES = new Set<string>(['admin', 'engineer', 'operator', 'auditor', 'viewer'])

/**
 * The console's role names are lower case, the GraphQL enum members are not.
 * Anything unrecognised is dropped rather than guessed: notifying the wrong role is
 * worse than notifying nobody, and the schema is the authority on what exists.
 */
function toUserRole(role: string | null | undefined): UserRole | undefined {
  const candidate = String(role ?? '').toLowerCase()
  return ROLES.has(candidate) ? (candidate as UserRole) : undefined
}

function toConsoleRole(role: UserRole): string {
  return role.toUpperCase()
}

export function graphqlAlertRuleToAlertRule(rule: GraphqlAlertRule): AlertRule {
  return {
    id: rule.id,
    name: rule.name,
    description: rule.description,
    enabled: rule.enabled,
    severity: (SEVERITIES.has(rule.severity) ? rule.severity : 'INFO') as AlarmSeverity,
    category: (CATEGORIES.has(rule.category) ? rule.category : 'CUSTOM') as AlarmCategory,
    topic: rule.topic,
    metricField: rule.metricField,
    condition: (CONDITIONS.has(rule.condition) ? rule.condition : 'EQUALS') as AlarmConditionType,
    thresholdValue: rule.thresholdValue,
    thresholdUpperValue: rule.thresholdUpperValue ?? undefined,
    unit: rule.unit ?? undefined,
    delaySeconds: Number(rule.delaySeconds ?? 0),
    targetRoles: rule.notifyRoles.map(toUserRole).filter((role): role is UserRole => !!role),
    escalationRole: toUserRole(rule.escalationRole),
    escalationTimeoutMinutes:
      rule.escalationTimeoutMinutes === null || rule.escalationTimeoutMinutes === undefined
        ? undefined
        : Number(rule.escalationTimeoutMinutes),
    autoResolveOnNormal: rule.autoResolveOnNormal,
    actions: {
      inAppNotification: rule.inAppNotification,
      audioChime: rule.audioChime,
      mqttPublishOnTrigger: rule.mqttPublishOnTrigger,
      mqttAlarmTopic: rule.mqttAlarmTopic ?? undefined,
      emailWebhook: rule.emailWebhook,
      webhookUrl: rule.webhookUrl ?? undefined,
    },
    triggerCount: Number(rule.triggerCount ?? 0),
    lastTriggeredAt: rule.lastTriggeredAt ?? undefined,
    lastEvaluatedAt: rule.lastEvaluatedAt ?? undefined,
    createdAt: rule.createdAt ?? new Date().toISOString(),
    updatedAt: rule.updatedAt ?? new Date().toISOString(),
  }
}

/**
 * A whole rule, as `AlertRuleInput` expects it.
 *
 * The counters and timestamps are deliberately absent: they are the server's, and a
 * browser must not be able to rewrite when an alarm last fired. An escalation
 * timeout of 0 is dropped too — the server reads that as "escalate immediately" and
 * rejects it, while the console's empty form field means "never".
 */
export function alertRuleToGraphqlInput(rule: AlertRule): Record<string, unknown> {
  return {
    id: rule.id,
    name: rule.name,
    description: rule.description ?? '',
    enabled: rule.enabled,
    severity: rule.severity,
    category: rule.category,
    topic: rule.topic,
    metricField: rule.metricField,
    condition: rule.condition,
    thresholdValue: rule.thresholdValue,
    thresholdUpperValue: rule.thresholdUpperValue ?? null,
    unit: rule.unit ?? null,
    delaySeconds: rule.delaySeconds ?? 0,
    escalationRole: rule.escalationRole ? toConsoleRole(rule.escalationRole) : null,
    escalationTimeoutMinutes: rule.escalationTimeoutMinutes ? rule.escalationTimeoutMinutes : null,
    notifyRoles: (rule.targetRoles ?? []).map(toConsoleRole),
    autoResolveOnNormal: rule.autoResolveOnNormal,
    inAppNotification: rule.actions.inAppNotification,
    audioChime: rule.actions.audioChime,
    mqttPublishOnTrigger: rule.actions.mqttPublishOnTrigger,
    mqttAlarmTopic: rule.actions.mqttAlarmTopic ?? null,
    emailWebhook: rule.actions.emailWebhook,
    webhookUrl: rule.actions.webhookUrl ?? null,
  }
}

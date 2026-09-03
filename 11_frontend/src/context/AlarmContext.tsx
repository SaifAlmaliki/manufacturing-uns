/**
 * Alarm & Alert Rule Management Context
 * Real-time threshold evaluation, role-targeted triggers, audio alerts, and audit logging.
 *
 * Alert Rules live in Postgres (`console.alert_rules`) via GraphQL. Active incidents
 * are raised only from live MQTT evaluation while the platform is online. No demo seed,
 * simulated triggers, or browser-persisted fake alarms.
 */

import React, { createContext, useContext, useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  AlertRule,
  ActiveAlarm,
  AlarmAuditEntry,
  AlarmSeverity,
  AlarmCategory,
  AlarmConditionType,
} from '../types/alarm';
import { UserRole } from '../types/rbac';
import { unsGraphQLClient } from '../services/graphql/client';
import { useAuth } from './AuthContext';
import { useUNS } from './UNSContext';

const STORAGE_KEYS = {
  AUDIO_MUTED: 'uns_alarm_audio_muted',
};

/** Legacy keys from demo-seed builds — removed on mount so stale fake alarms never reappear. */
const LEGACY_STORAGE_KEYS = [
  'uns_alert_rules_v1',
  'uns_alert_rules_v2',
  'uns_active_alarms_v1',
  'uns_alarm_audit_v1',
] as const;

/**
 * Where the rules on screen came from.
 *
 * `SERVER` means everyone at this site sees them. `BROWSER` means this tab is on its
 * own — the operator needs to know that, because a rule that only exists here will
 * not warn the next shift.
 */
export type AlertRuleOrigin = 'SERVER' | 'BROWSER';

interface AlarmContextType {
  rules: AlertRule[];
  activeAlarms: ActiveAlarm[];
  auditLog: AlarmAuditEntry[];
  isMuted: boolean;

  // Where the rules came from, and what went wrong reaching the server
  rulesOrigin: AlertRuleOrigin;
  rulesError: string | null;
  rulesLoading: boolean;
  /** True when GraphQL returned rules from Postgres — CRUD is allowed. */
  canPersistRules: boolean;
  /** True when the platform is reachable; incidents only evaluate against live MQTT then. */
  isPlatformLive: boolean;
  refreshRules: () => Promise<void>;

  // Computed role-specific counts & filters
  myRoleAlarms: ActiveAlarm[];
  myUnacknowledgedCount: number;
  totalUnacknowledgedCount: number;
  criticalAlarmsCount: number;
  
  // Rule Management (CRUD) — persists to Postgres via GraphQL; rejects when platform is offline
  createRule: (ruleData: Omit<AlertRule, 'id' | 'createdAt' | 'updatedAt' | 'triggerCount'>) => Promise<AlertRule>;
  updateRule: (ruleId: string, updates: Partial<AlertRule>) => Promise<void>;
  deleteRule: (ruleId: string) => void;
  toggleRuleEnabled: (ruleId: string, enabled: boolean) => void;
  
  // Alarm Lifecycle Operations
  acknowledgeAlarm: (alarmId: string, notes?: string) => void;
  resolveAlarm: (alarmId: string, notes?: string) => void;
  bulkAcknowledgeAll: (alarmIds?: string[]) => void;
  toggleAudioMute: () => void;
  playAlarmChime: (severity: AlarmSeverity) => void;
  clearResolvedAlarms: () => void;
}

const AlarmContext = createContext<AlarmContextType | null>(null);

export const AlarmProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { session, currentUser, isAdmin, roles } = useAuth();
  const { mqttFeed, health } = useUNS();

  const actorName = session?.displayName ?? session?.username ?? 'unknown';
  const actorRole = currentUser?.role ?? roles[0] ?? 'viewer';
  const actorLabel = `${actorName} (${actorRole})`;

  // Drop any demo-seed data left in the browser from earlier builds.
  useEffect(() => {
    try {
      for (const key of LEGACY_STORAGE_KEYS) {
        localStorage.removeItem(key);
      }
    } catch {
      // ignore
    }
  }, []);

  // Rules come from Postgres via GraphQL. No demo seed — empty until the platform responds.
  const [rules, setRules] = useState<AlertRule[]>([]);

  const [rulesOrigin, setRulesOrigin] = useState<AlertRuleOrigin>('BROWSER');
  const [rulesError, setRulesError] = useState<string | null>(null);
  const [rulesLoading, setRulesLoading] = useState(true);

  // Read by the loader without making it depend on every keystroke in the rule editor.
  const rulesRef = useRef(rules);
  useEffect(() => {
    rulesRef.current = rules;
  }, [rules]);

  const [activeAlarms, setActiveAlarms] = useState<ActiveAlarm[]>([]);
  const [auditLog, setAuditLog] = useState<AlarmAuditEntry[]>([]);

  const [isMuted, setIsMuted] = useState<boolean>(() => {
    try {
      return localStorage.getItem(STORAGE_KEYS.AUDIO_MUTED) === 'true';
    } catch {
      return false;
    }
  });

  /**
   * Load alert rules from Postgres via GraphQL.
   */
  const refreshRules = useCallback(async () => {
    setRulesLoading(true);
    try {
      const stored = await unsGraphQLClient.getAlertRules();

      if (stored === null) {
        setRules([]);
        setRulesOrigin('BROWSER');
        setRulesError(
          'Alert Rules could not be read from the platform (GraphQL offline). Start the backend on port 8000, then refresh.',
        );
        return;
      }

      setRules(stored);
      setRulesOrigin('SERVER');
      setRulesError(null);
    } finally {
      setRulesLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshRules();
  }, [refreshRules]);

  const isPlatformLive = health.graphqlHttp && rulesOrigin === 'SERVER';
  const canPersistRules = isPlatformLive && !rulesLoading;

  // Incidents are live MQTT evaluations only — clear them when the platform drops offline.
  useEffect(() => {
    if (!isPlatformLive) {
      setActiveAlarms([]);
      setAuditLog([]);
    }
  }, [isPlatformLive]);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEYS.AUDIO_MUTED, String(isMuted));
    } catch {
      // ignore
    }
  }, [isMuted]);

  // Audio Chime Synthesizer using Web Audio API
  const audioCtxRef = useRef<AudioContext | null>(null);

  const playAlarmChime = useCallback((severity: AlarmSeverity) => {
    if (isMuted) return;
    try {
      const AudioContextClass = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      if (!AudioContextClass) return;

      if (!audioCtxRef.current || audioCtxRef.current.state === 'suspended') {
        audioCtxRef.current = new AudioContextClass();
      }
      const ctx = audioCtxRef.current;
      if (ctx.state === 'suspended') {
        ctx.resume();
      }

      const now = ctx.currentTime;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();

      osc.connect(gain);
      gain.connect(ctx.destination);

      if (severity === 'CRITICAL') {
        // High urgency industrial two-tone pulse
        osc.type = 'sawtooth';
        osc.frequency.setValueAtTime(880, now);
        osc.frequency.setValueAtTime(660, now + 0.12);
        osc.frequency.setValueAtTime(880, now + 0.24);
        gain.gain.setValueAtTime(0.15, now);
        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.38);
        osc.start(now);
        osc.stop(now + 0.38);
      } else if (severity === 'HIGH') {
        // Major third warning chime
        osc.type = 'triangle';
        osc.frequency.setValueAtTime(659.25, now); // E5
        osc.frequency.setValueAtTime(783.99, now + 0.15); // G5
        gain.gain.setValueAtTime(0.12, now);
        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.35);
        osc.start(now);
        osc.stop(now + 0.35);
      } else {
        // Soft single alert pip for WARNING / INFO
        osc.type = 'sine';
        osc.frequency.setValueAtTime(523.25, now); // C5
        gain.gain.setValueAtTime(0.08, now);
        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.2);
        osc.start(now);
        osc.stop(now + 0.2);
      }
    } catch {
      // Audio playback fails gracefully if browser block policies apply
    }
  }, [isMuted]);

  // Log an Alarm Audit Entry
  const logAlarmAudit = useCallback((
    alarmId: string,
    ruleName: string,
    topic: string,
    severity: AlarmSeverity,
    action: AlarmAuditEntry['action'],
    details: string
  ) => {
    const newEntry: AlarmAuditEntry = {
      id: `aud-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      timestamp: new Date().toISOString(),
      alarmId,
      ruleName,
      topic,
      severity,
      action,
      actorName: session?.displayName ?? session?.username ?? 'unknown',
      actorRole: currentUser?.role ?? roles[0] ?? 'viewer',
      details,
    };
    setAuditLog((prev) => [newEntry, ...prev.slice(0, 199)]);
  }, [session, currentUser, roles]);

  // When each rule last had a quiet evaluation reported, so that the reporting below
  // stays rare. Not state: nothing renders from it.
  const lastQuietReportRef = useRef<Map<string, number>>(new Map());

  /**
   * Tell the platform a rule was evaluated.
   *
   * Breaches are always reported — they move a counter operators read. Quiet
   * evaluations are reported at most once a minute per rule, because a rule matching
   * a 1 Hz topic would otherwise turn every reading into an HTTP round trip to write
   * a timestamp nobody watches that closely. What the timestamp is for is answering
   * "is this rule still being evaluated at all", and a minute is enough for that.
   */
  const reportEvaluation = useCallback((ruleId: string, triggered: boolean) => {
    if (!triggered) {
      const previous = lastQuietReportRef.current.get(ruleId) ?? 0;
      const now = Date.now();
      if (now - previous < 60_000) return;
      lastQuietReportRef.current.set(ruleId, now);
    }
    void unsGraphQLClient.recordAlertRuleEvaluation(ruleId, triggered);
  }, []);

  // Evaluate Rule Condition Helper
  const evaluateCondition = (
    rule: AlertRule,
    value: unknown
  ): { breached: boolean; desc: string } => {
    if (value === undefined || value === null) {
      return { breached: false, desc: 'Value is null/undefined' };
    }

    const numVal = typeof value === 'number' ? value : parseFloat(String(value));
    const numThresh = typeof rule.thresholdValue === 'number' ? rule.thresholdValue : parseFloat(String(rule.thresholdValue));

    switch (rule.condition) {
      case 'GREATER_THAN': {
        const breached = !isNaN(numVal) && !isNaN(numThresh) && numVal > numThresh;
        return {
          breached,
          desc: `${rule.metricField} (${value}${rule.unit ? ' ' + rule.unit : ''}) > ${rule.thresholdValue}${rule.unit ? ' ' + rule.unit : ''}`,
        };
      }
      case 'LESS_THAN': {
        const breached = !isNaN(numVal) && !isNaN(numThresh) && numVal < numThresh;
        return {
          breached,
          desc: `${rule.metricField} (${value}${rule.unit ? ' ' + rule.unit : ''}) < ${rule.thresholdValue}${rule.unit ? ' ' + rule.unit : ''}`,
        };
      }
      case 'EQUALS': {
        const breached = String(value).toLowerCase() === String(rule.thresholdValue).toLowerCase();
        return {
          breached,
          desc: `${rule.metricField} (${value}) == ${rule.thresholdValue}`,
        };
      }
      case 'NOT_EQUALS': {
        const breached = String(value).toLowerCase() !== String(rule.thresholdValue).toLowerCase();
        return {
          breached,
          desc: `${rule.metricField} (${value}) != ${rule.thresholdValue}`,
        };
      }
      case 'RANGE_OUTSIDE': {
        const upper = rule.thresholdUpperValue ?? numThresh;
        const breached = !isNaN(numVal) && (numVal < numThresh || numVal > upper);
        return {
          breached,
          desc: `${rule.metricField} (${value}) outside [${numThresh}, ${upper}]${rule.unit ? ' ' + rule.unit : ''}`,
        };
      }
      case 'CONTAINS': {
        const breached = String(value).toLowerCase().includes(String(rule.thresholdValue).toLowerCase());
        return {
          breached,
          desc: `${rule.metricField} contains "${rule.thresholdValue}"`,
        };
      }
      default:
        return { breached: false, desc: '' };
    }
  };

  // Evaluate incoming MQTT payloads against enabled rules (live platform only)
  useEffect(() => {
    if (!isPlatformLive) return;
    if (mqttFeed.length === 0) return;
    const latestMessage = mqttFeed[0];
    if (!latestMessage || !latestMessage.payload || typeof latestMessage.payload !== 'object') return;

    const payloadObj = latestMessage.payload as Record<string, unknown>;

    rules.forEach((rule) => {
      if (!rule.enabled) return;

      // Check topic matching
      const topicMatches =
        rule.topic === '*' ||
        rule.topic === latestMessage.topic ||
        (rule.topic.endsWith('/#') && latestMessage.topic.startsWith(rule.topic.slice(0, -2))) ||
        (rule.topic.includes('/+') &&
          new RegExp('^' + rule.topic.replace(/\+/g, '[^/]+') + '$').test(latestMessage.topic));

      if (!topicMatches) return;

      // Extract metric field
      const rawVal = payloadObj[rule.metricField] ?? payloadObj['value'] ?? payloadObj[rule.metricField.toLowerCase()];
      if (rawVal === undefined) return;

      const evalResult = evaluateCondition(rule, rawVal);

      if (!evalResult.breached) {
        reportEvaluation(rule.id, false);
      }

      if (evalResult.breached) {
        // Check if alarm already exists for this rule and is active
        setActiveAlarms((prev) => {
          const existing = prev.find((a) => a.ruleId === rule.id && (a.status === 'ACTIVE_UNACK' || a.status === 'ACTIVE_ACK'));
          if (existing) {
            // Update current value
            return prev.map((a) =>
              a.id === existing.id
                ? { ...a, currentValue: rawVal, conditionDescription: evalResult.desc }
                : a
            );
          }

          // Trigger new alarm
          const newAlarm: ActiveAlarm = {
            id: `alm-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
            ruleId: rule.id,
            ruleName: rule.name,
            topic: latestMessage.topic,
            severity: rule.severity,
            category: rule.category,
            conditionDescription: evalResult.desc,
            currentValue: rawVal,
            unit: rule.unit,
            status: 'ACTIVE_UNACK',
            triggeredAt: new Date().toISOString(),
            targetRoles: rule.targetRoles,
            escalated: false,
          };

          // Play sound if enabled
          if (rule.actions.audioChime) {
            playAlarmChime(rule.severity);
          }

          // Increment rule trigger stats, here and on the platform. The counter is the
          // server's — every console that watches this rule adds to the same total —
          // but it is incremented locally too so the number moves without a round trip.
          setRules((rPrev) =>
            rPrev.map((r) =>
              r.id === rule.id
                ? { ...r, triggerCount: r.triggerCount + 1, lastTriggeredAt: new Date().toISOString() }
                : r
            )
          );
          reportEvaluation(rule.id, true);

          // Log to audit
          logAlarmAudit(
            newAlarm.id,
            rule.name,
            latestMessage.topic,
            rule.severity,
            'TRIGGERED',
            `Live threshold breach: ${evalResult.desc}. Target roles: ${rule.targetRoles.join(', ')}`
          );

          return [newAlarm, ...prev];
        });
      } else if (rule.autoResolveOnNormal) {
        // Automatically clear active alarm if metric returned to safe range
        setActiveAlarms((prev) => {
          const existing = prev.find((a) => a.ruleId === rule.id && (a.status === 'ACTIVE_UNACK' || a.status === 'ACTIVE_ACK'));
          if (!existing) return prev;

          logAlarmAudit(
            existing.id,
            rule.name,
            existing.topic,
            rule.severity,
            'CLEARED',
            `Value returned to safe range (${rawVal}). Auto-resolved.`
          );

          return prev.map((a) =>
            a.id === existing.id
              ? { ...a, status: 'RESOLVED', clearedAt: new Date().toISOString(), currentValue: rawVal }
              : a
          );
        });
      }
    });
  }, [mqttFeed, rules, isPlatformLive, playAlarmChime, logAlarmAudit, reportEvaluation]);

  // Filter alarms relevant to the current user's role
  const myRoleAlarms = useMemo(() => {
    // Admin & Auditor can view all alarms; other roles see alarms configured for their role
    if (isAdmin || roles.includes('auditor')) {
      return activeAlarms;
    }
    const role = currentUser?.role ?? roles[0];
    if (!role) {
      return [];
    }
    return activeAlarms.filter((a) => a.targetRoles.includes(role));
  }, [activeAlarms, currentUser?.role, isAdmin, roles]);

  const myUnacknowledgedCount = useMemo(() => {
    return myRoleAlarms.filter((a) => a.status === 'ACTIVE_UNACK').length;
  }, [myRoleAlarms]);

  const totalUnacknowledgedCount = useMemo(() => {
    return activeAlarms.filter((a) => a.status === 'ACTIVE_UNACK').length;
  }, [activeAlarms]);

  const criticalAlarmsCount = useMemo(() => {
    return activeAlarms.filter((a) => a.severity === 'CRITICAL' && a.status === 'ACTIVE_UNACK').length;
  }, [activeAlarms]);

  const requirePersistableRules = useCallback(() => {
    if (!canPersistRules) {
      throw new Error(
        rulesError ??
          'The platform database is not reachable. Alert Rules are stored in Postgres via GraphQL on port 8000.',
      );
    }
  }, [canPersistRules, rulesError]);

  // Operations
  const createRule = useCallback(async (
    ruleData: Omit<AlertRule, 'id' | 'createdAt' | 'updatedAt' | 'triggerCount'>
  ): Promise<AlertRule> => {
    requirePersistableRules();

    const draft: AlertRule = {
      ...ruleData,
      id: `rule-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      triggerCount: 0,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };

    const saved = await unsGraphQLClient.saveAlertRule(draft);
    setRules((prev) => [saved, ...prev]);
    setRulesOrigin('SERVER');
    setRulesError(null);
    logAlarmAudit(
      saved.id,
      saved.name,
      saved.topic,
      saved.severity,
      'RULE_UPDATED',
      `Created new alert rule targeted to roles: ${saved.targetRoles.join(', ')}`,
    );
    return saved;
  }, [logAlarmAudit, requirePersistableRules]);

  const updateRule = useCallback(async (ruleId: string, updates: Partial<AlertRule>) => {
    requirePersistableRules();

    const current = rulesRef.current.find((r) => r.id === ruleId);
    if (!current) return;

    const updated: AlertRule = { ...current, ...updates, updatedAt: new Date().toISOString() };
    const saved = await unsGraphQLClient.saveAlertRule(updated);
    setRules((prev) => prev.map((r) => (r.id === saved.id ? saved : r)));
    setRulesOrigin('SERVER');
    setRulesError(null);
    logAlarmAudit(
      saved.id,
      saved.name,
      saved.topic,
      saved.severity,
      'RULE_UPDATED',
      `Updated alert rule configuration (Target Roles: ${saved.targetRoles.join(', ')})`,
    );
  }, [logAlarmAudit, requirePersistableRules]);

  const deleteRule = useCallback((ruleId: string) => {
    const target = rules.find((r) => r.id === ruleId);
    if (target) {
      logAlarmAudit(
        target.id,
        target.name,
        target.topic,
        target.severity,
        'RULE_UPDATED',
        `Deleted alert rule '${target.name}'`
      );
    }
    setRules((prev) => prev.filter((r) => r.id !== ruleId));
    unsGraphQLClient.deleteAlertRule(ruleId).catch((error: unknown) => {
      setRulesError(
        `'${target?.name ?? ruleId}' is still stored on the platform: ${
          error instanceof Error ? error.message : 'the delete did not reach it'
        }`
      );
    });
  }, [rules, logAlarmAudit]);

  const toggleRuleEnabled = useCallback((ruleId: string, enabled: boolean) => {
    setRules((prev) =>
      prev.map((r) => (r.id === ruleId ? { ...r, enabled, updatedAt: new Date().toISOString() } : r))
    );
    // Its own mutation rather than a full save: muting an alarm must be one click, and
    // it must not be able to rewrite a threshold on the way.
    unsGraphQLClient
      .setAlertRuleEnabled(ruleId, enabled)
      .then((saved) => {
        if (saved) {
          setRules((prev) => prev.map((r) => (r.id === saved.id ? saved : r)));
        }
      })
      .catch((error: unknown) => {
        setRulesError(
          `${enabled ? 'Arming' : 'Muting'} that rule did not reach the platform: ${
            error instanceof Error ? error.message : 'unknown error'
          }`
        );
      });
  }, []);

  const acknowledgeAlarm = useCallback((alarmId: string, notes?: string) => {
    setActiveAlarms((prev) =>
      prev.map((a) => {
        if (a.id === alarmId) {
          const updated: ActiveAlarm = {
            ...a,
            status: 'ACTIVE_ACK',
            acknowledgedAt: new Date().toISOString(),
            acknowledgedBy: actorLabel,
            notes: notes || a.notes,
          };
          logAlarmAudit(
            a.id,
            a.ruleName,
            a.topic,
            a.severity,
            'ACKNOWLEDGED',
            `Acknowledged by ${actorLabel}. ${notes ? 'Note: ' + notes : ''}`
          );
          return updated;
        }
        return a;
      })
    );
  }, [actorLabel, logAlarmAudit]);

  const resolveAlarm = useCallback((alarmId: string, notes?: string) => {
    setActiveAlarms((prev) =>
      prev.map((a) => {
        if (a.id === alarmId) {
          const updated: ActiveAlarm = {
            ...a,
            status: 'RESOLVED',
            clearedAt: new Date().toISOString(),
            notes: notes ? `${a.notes ? a.notes + ' | ' : ''}Resolved: ${notes}` : a.notes,
          };
          logAlarmAudit(
            a.id,
            a.ruleName,
            a.topic,
            a.severity,
            'RESOLVED',
            `Marked as RESOLVED by ${actorName}. ${notes ? 'Resolution: ' + notes : ''}`
          );
          return updated;
        }
        return a;
      })
    );
  }, [actorName, logAlarmAudit]);

  const bulkAcknowledgeAll = useCallback((alarmIds?: string[]) => {
    setActiveAlarms((prev) =>
      prev.map((a) => {
        if (a.status === 'ACTIVE_UNACK' && (!alarmIds || alarmIds.includes(a.id))) {
          logAlarmAudit(
            a.id,
            a.ruleName,
            a.topic,
            a.severity,
            'ACKNOWLEDGED',
            `Bulk acknowledged by ${actorLabel}`
          );
          return {
            ...a,
            status: 'ACTIVE_ACK',
            acknowledgedAt: new Date().toISOString(),
            acknowledgedBy: actorLabel,
          };
        }
        return a;
      })
    );
  }, [actorLabel, logAlarmAudit]);

  const toggleAudioMute = useCallback(() => {
    setIsMuted((prev) => !prev);
  }, []);

  const clearResolvedAlarms = useCallback(() => {
    setActiveAlarms((prev) => prev.filter((a) => a.status !== 'RESOLVED'));
  }, []);

  return (
    <AlarmContext.Provider
      value={{
        rules,
        activeAlarms,
        auditLog,
        isMuted,
        rulesOrigin,
        rulesError,
        rulesLoading,
        canPersistRules,
        isPlatformLive,
        refreshRules,
        myRoleAlarms,
        myUnacknowledgedCount,
        totalUnacknowledgedCount,
        criticalAlarmsCount,
        createRule,
        updateRule,
        deleteRule,
        toggleRuleEnabled,
        acknowledgeAlarm,
        resolveAlarm,
        bulkAcknowledgeAll,
        toggleAudioMute,
        playAlarmChime,
        clearResolvedAlarms,
      }}
    >
      {children}
    </AlarmContext.Provider>
  );
};

export const useAlarms = (): AlarmContextType => {
  const context = useContext(AlarmContext);
  if (!context) {
    throw new Error('useAlarms must be used within an AlarmProvider');
  }
  return context;
};

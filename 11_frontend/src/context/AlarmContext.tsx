/**
 * Alarm & Alert Rule Management Context
 * Real-time threshold evaluation, role-targeted triggers, audio alerts, and audit logging.
 *
 * Alert Rules are plant configuration and live in Postgres, reached over GraphQL
 * (ADR-0005). localStorage is only a cache now, so that a console whose backend is
 * unreachable still renders the rules it last saw instead of an empty alarm list.
 * The active alarms and the audit trail are still browser-local — evaluation happens
 * here, and moving it to a service is a separate piece of work.
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
  RULES: 'uns_alert_rules_v1',
  ACTIVE_ALARMS: 'uns_active_alarms_v1',
  ALARM_AUDIT: 'uns_alarm_audit_v1',
  AUDIO_MUTED: 'uns_alarm_audio_muted',
};

/**
 * Where the rules on screen came from.
 *
 * `SERVER` means everyone at this site sees them. `BROWSER` means this tab is on its
 * own — the operator needs to know that, because a rule that only exists here will
 * not warn the next shift.
 */
export type AlertRuleOrigin = 'SERVER' | 'BROWSER';

const INITIAL_RULES: AlertRule[] = [
  {
    id: 'rule-temp-01',
    name: 'Reactor 01 Core Temp High-High',
    description: 'Triggers when Dormagen Polyurethane Reactor 01 core vessel temperature exceeds maximum safe run envelope of 85°C.',
    enabled: true,
    severity: 'CRITICAL',
    category: 'TEMPERATURE',
    topic: 'CovestroAG/Dormagen/Polyurethane/Reactor_01/temperature',
    metricField: 'temp_celsius',
    condition: 'GREATER_THAN',
    thresholdValue: 85,
    unit: '°C',
    delaySeconds: 0,
    targetRoles: ['operator', 'engineer', 'admin'],
    escalationRole: 'admin',
    escalationTimeoutMinutes: 5,
    autoResolveOnNormal: true,
    actions: {
      inAppNotification: true,
      audioChime: true,
      mqttPublishOnTrigger: true,
      mqttAlarmTopic: 'alarms/Dormagen/Reactor_01/high_temp',
      emailWebhook: true,
      webhookUrl: 'https://ops-webhook.covestro.internal/alerts/reactor1',
    },
    triggerCount: 8,
    lastTriggeredAt: new Date(Date.now() - 1000 * 60 * 18).toISOString(),
    createdAt: '2026-01-20T08:00:00.000Z',
    updatedAt: '2026-08-20T12:00:00.000Z',
  },
  {
    id: 'rule-press-02',
    name: 'Extrusion Line 2 Pressure Relief Trip',
    description: 'Monitors hydraulic melt accumulator pressure on Line 2. Immediate trip threshold at 135 bar.',
    enabled: true,
    severity: 'HIGH',
    category: 'PRESSURE',
    topic: 'CovestroAG/Krefeld_Uerdingen/Polycarbonates/Extrusion_Line_02/pressure',
    metricField: 'pressure_bar',
    condition: 'GREATER_THAN',
    thresholdValue: 135,
    unit: 'bar',
    delaySeconds: 2,
    targetRoles: ['operator', 'engineer'],
    escalationRole: 'admin',
    escalationTimeoutMinutes: 10,
    autoResolveOnNormal: true,
    actions: {
      inAppNotification: true,
      audioChime: true,
      mqttPublishOnTrigger: true,
      mqttAlarmTopic: 'alarms/Krefeld/Extruder_02/overpressure',
      emailWebhook: false,
    },
    triggerCount: 3,
    lastTriggeredAt: new Date(Date.now() - 1000 * 60 * 45).toISOString(),
    createdAt: '2026-02-15T09:30:00.000Z',
    updatedAt: '2026-07-10T14:20:00.000Z',
  },
  {
    id: 'rule-vib-03',
    name: 'MDI Distillation Pump Vibration RMS',
    description: 'Bearing wear indicator on primary charge pump. Warning when RMS vibration exceeds 4.5 mm/s.',
    enabled: true,
    severity: 'WARNING',
    category: 'VIBRATION',
    topic: 'CovestroAG/Leverkusen/MDI/Distillation_Column/vibration',
    metricField: 'vibration_rms',
    condition: 'GREATER_THAN',
    thresholdValue: 4.5,
    unit: 'mm/s',
    delaySeconds: 5,
    targetRoles: ['engineer', 'admin'],
    escalationRole: 'admin',
    escalationTimeoutMinutes: 15,
    autoResolveOnNormal: true,
    actions: {
      inAppNotification: true,
      audioChime: false,
      mqttPublishOnTrigger: false,
      emailWebhook: true,
    },
    triggerCount: 12,
    lastTriggeredAt: new Date(Date.now() - 1000 * 60 * 120).toISOString(),
    createdAt: '2026-03-01T11:00:00.000Z',
    updatedAt: '2026-08-01T16:45:00.000Z',
  },
  {
    id: 'rule-flow-04',
    name: 'Antwerp Curing Oven Scrubber Flow Low',
    description: 'Exhaust gas scrubber intake must maintain above 140 m³/h to satisfy environmental compliance specs.',
    enabled: true,
    severity: 'HIGH',
    category: 'FLOW_RATE',
    topic: 'CovestroAG/Antwerp/Elastomers/Curing_Oven/flow',
    metricField: 'flow_rate',
    condition: 'LESS_THAN',
    thresholdValue: 140,
    unit: 'm³/h',
    delaySeconds: 3,
    targetRoles: ['operator', 'engineer', 'auditor'],
    escalationRole: 'admin',
    escalationTimeoutMinutes: 10,
    autoResolveOnNormal: true,
    actions: {
      inAppNotification: true,
      audioChime: true,
      mqttPublishOnTrigger: true,
      emailWebhook: true,
    },
    triggerCount: 2,
    lastTriggeredAt: new Date(Date.now() - 1000 * 60 * 95).toISOString(),
    createdAt: '2026-04-10T14:15:00.000Z',
    updatedAt: '2026-08-15T10:00:00.000Z',
  },
  {
    id: 'rule-spark-05',
    name: 'Sparkplug B Edge Node Death Notice (NDEATH)',
    description: 'Instant alert when an edge gateway transmits an NDEATH payload or drops MQTT connection.',
    enabled: true,
    severity: 'CRITICAL',
    category: 'NODE_OFFLINE',
    topic: 'spBv1.0/CovestroAG/NDEATH/#',
    metricField: 'online',
    condition: 'EQUALS',
    thresholdValue: false,
    delaySeconds: 0,
    targetRoles: ['operator', 'engineer', 'admin'],
    escalationRole: 'admin',
    escalationTimeoutMinutes: 3,
    autoResolveOnNormal: false,
    actions: {
      inAppNotification: true,
      audioChime: true,
      mqttPublishOnTrigger: true,
      emailWebhook: true,
    },
    triggerCount: 4,
    lastTriggeredAt: new Date(Date.now() - 1000 * 60 * 6).toISOString(),
    createdAt: '2026-05-01T08:00:00.000Z',
    updatedAt: '2026-08-25T11:15:00.000Z',
  },
  {
    id: 'rule-stale-06',
    name: 'Global UNS Telemetry Stale Timeout',
    description: 'Detects any leaf sensor node that has ceased publishing updates for greater than 5 minutes.',
    enabled: true,
    severity: 'WARNING',
    category: 'STALE_TIMEOUT',
    topic: '*',
    metricField: 'isStale',
    condition: 'EQUALS',
    thresholdValue: true,
    targetRoles: ['engineer', 'admin', 'auditor'],
    escalationRole: 'admin',
    escalationTimeoutMinutes: 30,
    autoResolveOnNormal: true,
    actions: {
      inAppNotification: true,
      audioChime: false,
      mqttPublishOnTrigger: false,
      emailWebhook: false,
    },
    triggerCount: 19,
    lastTriggeredAt: new Date(Date.now() - 1000 * 60 * 30).toISOString(),
    createdAt: '2026-05-15T10:00:00.000Z',
    updatedAt: '2026-08-28T09:00:00.000Z',
  },
];

const INITIAL_ACTIVE_ALARMS: ActiveAlarm[] = [
  {
    id: 'alm-act-001',
    ruleId: 'rule-temp-01',
    ruleName: 'Reactor 01 Core Temp High-High',
    topic: 'CovestroAG/Dormagen/Polyurethane/Reactor_01/temperature',
    severity: 'CRITICAL',
    category: 'TEMPERATURE',
    conditionDescription: 'temp_celsius (88.4 °C) > 85.0 °C',
    currentValue: 88.4,
    unit: '°C',
    status: 'ACTIVE_UNACK',
    triggeredAt: new Date(Date.now() - 1000 * 60 * 4).toISOString(),
    targetRoles: ['operator', 'engineer', 'admin'],
    escalated: false,
  },
  {
    id: 'alm-act-002',
    ruleId: 'rule-press-02',
    ruleName: 'Extrusion Line 2 Pressure Relief Trip',
    topic: 'CovestroAG/Krefeld_Uerdingen/Polycarbonates/Extrusion_Line_02/pressure',
    severity: 'HIGH',
    category: 'PRESSURE',
    conditionDescription: 'pressure_bar (139.2 bar) > 135.0 bar',
    currentValue: 139.2,
    unit: 'bar',
    status: 'ACTIVE_ACK',
    triggeredAt: new Date(Date.now() - 1000 * 60 * 22).toISOString(),
    acknowledgedAt: new Date(Date.now() - 1000 * 60 * 18).toISOString(),
    acknowledgedBy: 'Marcus Weber (Operator)',
    notes: 'Hydraulic bleed bypass valve engaged. Cooling cycle in progress.',
    targetRoles: ['operator', 'engineer'],
    escalated: false,
  },
  {
    id: 'alm-act-003',
    ruleId: 'rule-vib-03',
    ruleName: 'MDI Distillation Pump Vibration RMS',
    topic: 'CovestroAG/Leverkusen/MDI/Distillation_Column/vibration',
    severity: 'WARNING',
    category: 'VIBRATION',
    conditionDescription: 'vibration_rms (4.82 mm/s) > 4.50 mm/s',
    currentValue: 4.82,
    unit: 'mm/s',
    status: 'ACTIVE_UNACK',
    triggeredAt: new Date(Date.now() - 1000 * 60 * 55).toISOString(),
    targetRoles: ['engineer', 'admin'],
    escalated: false,
  },
];

const INITIAL_ALARM_AUDIT: AlarmAuditEntry[] = [
  {
    id: 'aud-alm-101',
    timestamp: new Date(Date.now() - 1000 * 60 * 4).toISOString(),
    alarmId: 'alm-act-001',
    ruleName: 'Reactor 01 Core Temp High-High',
    topic: 'CovestroAG/Dormagen/Polyurethane/Reactor_01/temperature',
    severity: 'CRITICAL',
    action: 'TRIGGERED',
    actorName: 'UNS Ingestion Engine',
    actorRole: 'admin',
    details: 'Exceeded threshold 85°C (Current value: 88.4°C). Routed to Operator, Engineer, Admin.',
  },
  {
    id: 'aud-alm-102',
    timestamp: new Date(Date.now() - 1000 * 60 * 18).toISOString(),
    alarmId: 'alm-act-002',
    ruleName: 'Extrusion Line 2 Pressure Relief Trip',
    topic: 'CovestroAG/Krefeld_Uerdingen/Polycarbonates/Extrusion_Line_02/pressure',
    severity: 'HIGH',
    action: 'ACKNOWLEDGED',
    actorName: 'Marcus Weber',
    actorRole: 'operator',
    details: 'Acknowledged incident with operator note: Hydraulic bleed bypass valve engaged.',
  },
  {
    id: 'aud-alm-103',
    timestamp: new Date(Date.now() - 1000 * 60 * 120).toISOString(),
    alarmId: 'alm-prev-099',
    ruleName: 'Antwerp Curing Oven Scrubber Flow Low',
    topic: 'CovestroAG/Antwerp/Elastomers/Curing_Oven/flow',
    severity: 'HIGH',
    action: 'RESOLVED',
    actorName: 'Elena Rostova',
    actorRole: 'engineer',
    details: 'Flow restored to 152 m³/h. Alarm cleared and marked resolved.',
  },
];

interface AlarmContextType {
  rules: AlertRule[];
  activeAlarms: ActiveAlarm[];
  auditLog: AlarmAuditEntry[];
  isMuted: boolean;

  // Where the rules came from, and what went wrong reaching the server
  rulesOrigin: AlertRuleOrigin;
  rulesError: string | null;
  refreshRules: () => Promise<void>;

  // Computed role-specific counts & filters
  myRoleAlarms: ActiveAlarm[];
  myUnacknowledgedCount: number;
  totalUnacknowledgedCount: number;
  criticalAlarmsCount: number;
  
  // Rule Management (CRUD)
  createRule: (ruleData: Omit<AlertRule, 'id' | 'createdAt' | 'updatedAt' | 'triggerCount'>) => AlertRule;
  updateRule: (ruleId: string, updates: Partial<AlertRule>) => void;
  deleteRule: (ruleId: string) => void;
  toggleRuleEnabled: (ruleId: string, enabled: boolean) => void;
  testTriggerRule: (ruleId: string) => void;
  
  // Alarm Lifecycle Operations
  acknowledgeAlarm: (alarmId: string, notes?: string) => void;
  resolveAlarm: (alarmId: string, notes?: string) => void;
  bulkAcknowledgeAll: (alarmIds?: string[]) => void;
  toggleAudioMute: () => void;
  playAlarmChime: (severity: AlarmSeverity) => void;
  clearResolvedAlarms: () => void;
  restoreDefaultRules: () => void;
}

const AlarmContext = createContext<AlarmContextType | null>(null);

export const AlarmProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { currentUser } = useAuth();
  const { mqttFeed } = useUNS();

  // The cached rules render first so the alarm list is never briefly empty; the
  // server's answer replaces them as soon as it arrives.
  const [rules, setRules] = useState<AlertRule[]>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEYS.RULES);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed) && parsed.length > 0) return parsed;
      }
    } catch {
      // ignore
    }
    return INITIAL_RULES;
  });

  const [rulesOrigin, setRulesOrigin] = useState<AlertRuleOrigin>('BROWSER');
  const [rulesError, setRulesError] = useState<string | null>(null);

  // Read by the loader without making it depend on every keystroke in the rule editor.
  const rulesRef = useRef(rules);
  useEffect(() => {
    rulesRef.current = rules;
  }, [rules]);

  const [activeAlarms, setActiveAlarms] = useState<ActiveAlarm[]>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEYS.ACTIVE_ALARMS);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed)) return parsed;
      }
    } catch {
      // ignore
    }
    return INITIAL_ACTIVE_ALARMS;
  });

  const [auditLog, setAuditLog] = useState<AlarmAuditEntry[]>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEYS.ALARM_AUDIT);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed) && parsed.length > 0) return parsed;
      }
    } catch {
      // ignore
    }
    return INITIAL_ALARM_AUDIT;
  });

  const [isMuted, setIsMuted] = useState<boolean>(() => {
    try {
      return localStorage.getItem(STORAGE_KEYS.AUDIO_MUTED) === 'true';
    } catch {
      return false;
    }
  });

  /**
   * Load the rules the platform holds, and hand over this browser's rules if it holds none.
   *
   * The import is the migration path off localStorage: rules authored before the
   * server could store them would otherwise stay invisible to everybody else. It
   * only runs when the server has no rules at all, so it cannot resurrect a rule
   * somebody deliberately deleted elsewhere.
   */
  const refreshRules = useCallback(async () => {
    const stored = await unsGraphQLClient.getAlertRules();

    if (stored === null) {
      setRulesOrigin('BROWSER');
      setRulesError('Alert Rules could not be read from the platform. Showing this browser\'s cached copy.');
      return;
    }

    if (stored.length > 0) {
      setRules(stored);
      setRulesOrigin('SERVER');
      setRulesError(null);
      return;
    }

    try {
      const imported = await unsGraphQLClient.saveAlertRules(rulesRef.current);
      setRules(imported);
      setRulesOrigin('SERVER');
      setRulesError(null);
    } catch (error) {
      setRulesOrigin('BROWSER');
      setRulesError(error instanceof Error ? error.message : 'Alert Rules could not be stored');
    }
  }, []);

  useEffect(() => {
    void refreshRules();
  }, [refreshRules]);

  // Persistent storage effects. The rules are cached rather than owned here: see refreshRules.
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEYS.RULES, JSON.stringify(rules));
    } catch {
      // ignore
    }
  }, [rules]);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEYS.ACTIVE_ALARMS, JSON.stringify(activeAlarms));
    } catch {
      // ignore
    }
  }, [activeAlarms]);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEYS.ALARM_AUDIT, JSON.stringify(auditLog));
    } catch {
      // ignore
    }
  }, [auditLog]);

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
      actorName: currentUser.name,
      actorRole: currentUser.role,
      details,
    };
    setAuditLog((prev) => [newEntry, ...prev.slice(0, 199)]);
  }, [currentUser]);

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

  // Evaluate incoming MQTT payloads against enabled rules
  useEffect(() => {
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
  }, [mqttFeed, rules, playAlarmChime, logAlarmAudit, reportEvaluation]);

  // Filter alarms relevant to the current user's role
  const myRoleAlarms = useMemo(() => {
    // Admin & Auditor can view all alarms; other roles see alarms configured for their role
    if (currentUser.role === 'admin' || currentUser.role === 'auditor') {
      return activeAlarms;
    }
    return activeAlarms.filter((a) => a.targetRoles.includes(currentUser.role));
  }, [activeAlarms, currentUser.role]);

  const myUnacknowledgedCount = useMemo(() => {
    return myRoleAlarms.filter((a) => a.status === 'ACTIVE_UNACK').length;
  }, [myRoleAlarms]);

  const totalUnacknowledgedCount = useMemo(() => {
    return activeAlarms.filter((a) => a.status === 'ACTIVE_UNACK').length;
  }, [activeAlarms]);

  const criticalAlarmsCount = useMemo(() => {
    return activeAlarms.filter((a) => a.severity === 'CRITICAL' && a.status === 'ACTIVE_UNACK').length;
  }, [activeAlarms]);

  /**
   * Persist a whole rule, and adopt the row the server stored.
   *
   * The UI has already changed by the time this runs — an alarm form that waits for a
   * round trip feels broken — so a failure surfaces as `rulesError` rather than by
   * reverting under the operator's cursor. `refreshRules` is how they get back to
   * whatever the platform actually holds.
   */
  const persistRule = useCallback((rule: AlertRule) => {
    unsGraphQLClient
      .saveAlertRule(rule)
      .then((saved) => {
        setRules((prev) => prev.map((r) => (r.id === saved.id ? saved : r)));
        setRulesOrigin('SERVER');
        setRulesError(null);
      })
      .catch((error: unknown) => {
        setRulesOrigin('BROWSER');
        setRulesError(
          `'${rule.name}' is only stored in this browser: ${
            error instanceof Error ? error.message : 'the platform rejected it'
          }`
        );
      });
  }, []);

  // Operations
  const createRule = useCallback((
    ruleData: Omit<AlertRule, 'id' | 'createdAt' | 'updatedAt' | 'triggerCount'>
  ): AlertRule => {
    const newRule: AlertRule = {
      ...ruleData,
      id: `rule-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      triggerCount: 0,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };

    setRules((prev) => [newRule, ...prev]);
    persistRule(newRule);
    logAlarmAudit(
      newRule.id,
      newRule.name,
      newRule.topic,
      newRule.severity,
      'RULE_UPDATED',
      `Created new alert rule targeted to roles: ${newRule.targetRoles.join(', ')}`
    );
    return newRule;
  }, [logAlarmAudit, persistRule]);

  const updateRule = useCallback((ruleId: string, updates: Partial<AlertRule>) => {
    // Merged here rather than sent as a patch: the server stores whole rules, because
    // there is no safe meaning for "change the threshold of an alarm I have not read".
    const current = rulesRef.current.find((r) => r.id === ruleId);
    if (!current) return;

    const updated: AlertRule = { ...current, ...updates, updatedAt: new Date().toISOString() };
    setRules((prev) => prev.map((r) => (r.id === ruleId ? updated : r)));
    persistRule(updated);
    logAlarmAudit(
      updated.id,
      updated.name,
      updated.topic,
      updated.severity,
      'RULE_UPDATED',
      `Updated alert rule configuration (Target Roles: ${updated.targetRoles.join(', ')})`
    );
  }, [logAlarmAudit, persistRule]);

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

  const testTriggerRule = useCallback((ruleId: string) => {
    const rule = rules.find((r) => r.id === ruleId);
    if (!rule) return;

    const testValue = typeof rule.thresholdValue === 'number'
      ? rule.condition === 'LESS_THAN'
        ? Number(rule.thresholdValue) - 5
        : Number(rule.thresholdValue) + 12.5
      : rule.thresholdValue;

    const evalResult = evaluateCondition(rule, testValue);

    const testAlarm: ActiveAlarm = {
      id: `alm-test-${Date.now()}`,
      ruleId: rule.id,
      ruleName: `[TEST TRIGGER] ${rule.name}`,
      topic: rule.topic === '*' ? 'CovestroAG/Dormagen/Polyurethane/Reactor_01/temperature' : rule.topic,
      severity: rule.severity,
      category: rule.category,
      conditionDescription: `${evalResult.desc} (Manual Diagnostic Trigger)`,
      currentValue: testValue,
      unit: rule.unit,
      status: 'ACTIVE_UNACK',
      triggeredAt: new Date().toISOString(),
      targetRoles: rule.targetRoles,
      escalated: false,
    };

    if (rule.actions.audioChime) {
      playAlarmChime(rule.severity);
    }

    // Deliberately not counted, and not reported to the platform: `triggerCount` and
    // `lastTriggeredAt` now say how often the plant tripped this rule, shared with
    // everybody. A diagnostic run by one engineer must not read as a real trip to the
    // next shift. The test alarm and its audit entry are what the test is for.
    setActiveAlarms((prev) => [testAlarm, ...prev]);

    logAlarmAudit(
      testAlarm.id,
      rule.name,
      testAlarm.topic,
      rule.severity,
      'TRIGGERED',
      `Manual test alarm simulated by ${currentUser.name} (${currentUser.role}). Target roles: ${rule.targetRoles.join(', ')}`
    );
  }, [rules, currentUser, playAlarmChime, logAlarmAudit]);

  const acknowledgeAlarm = useCallback((alarmId: string, notes?: string) => {
    setActiveAlarms((prev) =>
      prev.map((a) => {
        if (a.id === alarmId) {
          const updated: ActiveAlarm = {
            ...a,
            status: 'ACTIVE_ACK',
            acknowledgedAt: new Date().toISOString(),
            acknowledgedBy: `${currentUser.name} (${currentUser.role})`,
            notes: notes || a.notes,
          };
          logAlarmAudit(
            a.id,
            a.ruleName,
            a.topic,
            a.severity,
            'ACKNOWLEDGED',
            `Acknowledged by ${currentUser.name} (${currentUser.role}). ${notes ? 'Note: ' + notes : ''}`
          );
          return updated;
        }
        return a;
      })
    );
  }, [currentUser, logAlarmAudit]);

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
            `Marked as RESOLVED by ${currentUser.name}. ${notes ? 'Resolution: ' + notes : ''}`
          );
          return updated;
        }
        return a;
      })
    );
  }, [currentUser, logAlarmAudit]);

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
            `Bulk acknowledged by ${currentUser.name} (${currentUser.role})`
          );
          return {
            ...a,
            status: 'ACTIVE_ACK',
            acknowledgedAt: new Date().toISOString(),
            acknowledgedBy: `${currentUser.name} (${currentUser.role})`,
          };
        }
        return a;
      })
    );
  }, [currentUser, logAlarmAudit]);

  const toggleAudioMute = useCallback(() => {
    setIsMuted((prev) => !prev);
  }, []);

  const clearResolvedAlarms = useCallback(() => {
    setActiveAlarms((prev) => prev.filter((a) => a.status !== 'RESOLVED'));
  }, []);

  /**
   * Put the demonstration rules back, on the platform as well as on screen.
   *
   * The rules are shared now, so this is not a local reset: anything authored on top of
   * the defaults is removed for everyone. The alarms and the audit trail stay browser-
   * local, so those really are just cleared here.
   */
  const restoreDefaultRules = useCallback(() => {
    const defaultIds = new Set(INITIAL_RULES.map((r) => r.id));
    const strays = rulesRef.current.filter((r) => !defaultIds.has(r.id)).map((r) => r.id);

    setRules(INITIAL_RULES);
    setActiveAlarms(INITIAL_ACTIVE_ALARMS);
    setAuditLog(INITIAL_ALARM_AUDIT);
    try {
      localStorage.removeItem(STORAGE_KEYS.ACTIVE_ALARMS);
      localStorage.removeItem(STORAGE_KEYS.ALARM_AUDIT);
    } catch {
      // ignore
    }

    void (async () => {
      try {
        await Promise.all(strays.map((id) => unsGraphQLClient.deleteAlertRule(id)));
        const restored = await unsGraphQLClient.saveAlertRules(INITIAL_RULES);
        setRules(restored);
        setRulesOrigin('SERVER');
        setRulesError(null);
      } catch (error) {
        setRulesOrigin('BROWSER');
        setRulesError(
          `The defaults were restored in this browser only: ${
            error instanceof Error ? error.message : 'the platform could not be reached'
          }`
        );
      }
    })();
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
        refreshRules,
        myRoleAlarms,
        myUnacknowledgedCount,
        totalUnacknowledgedCount,
        criticalAlarmsCount,
        createRule,
        updateRule,
        deleteRule,
        toggleRuleEnabled,
        testTriggerRule,
        acknowledgeAlarm,
        resolveAlarm,
        bulkAcknowledgeAll,
        toggleAudioMute,
        playAlarmChime,
        clearResolvedAlarms,
        restoreDefaultRules,
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

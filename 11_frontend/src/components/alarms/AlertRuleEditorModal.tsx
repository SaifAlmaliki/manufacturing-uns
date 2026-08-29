import React, { useState } from 'react';
import {
  X,
  AlertTriangle,
  Sliders,
  Shield,
  Bell,
  Volume2,
  Send,
  Mail,
  Layers,
  Check,
  Radio,
  ChevronDown,
} from 'lucide-react';
import {
  AlertRule,
  AlarmSeverity,
  AlarmCategory,
  AlarmConditionType,
} from '../../types/alarm';
import { UserRole, ROLE_CONFIGS } from '../../types/rbac';
import { useAlarms } from '../../context/AlarmContext';
import { useUNS } from '../../context/UNSContext';

interface AlertRuleEditorModalProps {
  rule: AlertRule | null;
  onClose: () => void;
}

const CATEGORIES: AlarmCategory[] = [
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
];

const SEVERITIES: AlarmSeverity[] = ['CRITICAL', 'HIGH', 'WARNING', 'INFO'];

const CONDITIONS: { label: string; value: AlarmConditionType }[] = [
  { label: 'Greater Than (> Threshold)', value: 'GREATER_THAN' },
  { label: 'Less Than (< Threshold)', value: 'LESS_THAN' },
  { label: 'Equals (== Exact Value)', value: 'EQUALS' },
  { label: 'Not Equals (!= Value)', value: 'NOT_EQUALS' },
  { label: 'Range Outside [Min, Max]', value: 'RANGE_OUTSIDE' },
  { label: 'Stale Timeout (No update for X min)', value: 'STALE_TIMEOUT' },
  { label: 'Payload String Contains', value: 'CONTAINS' },
];

const PREDEFINED_ROLES: UserRole[] = ['operator', 'engineer', 'admin', 'auditor', 'viewer'];

export const AlertRuleEditorModal: React.FC<AlertRuleEditorModalProps> = ({
  rule,
  onClose,
}) => {
  const { createRule, updateRule } = useAlarms();
  const { allLoadedNodes } = useUNS();

  const [name, setName] = useState(rule?.name || '');
  const [description, setDescription] = useState(rule?.description || '');
  const [category, setCategory] = useState<AlarmCategory>(rule?.category || 'TEMPERATURE');
  const [severity, setSeverity] = useState<AlarmSeverity>(rule?.severity || 'HIGH');
  const [topic, setTopic] = useState(rule?.topic || 'CovestroAG/Dormagen/Polyurethane/Reactor_01/temperature');
  const [metricField, setMetricField] = useState(rule?.metricField || 'temp_celsius');
  const [condition, setCondition] = useState<AlarmConditionType>(rule?.condition || 'GREATER_THAN');
  const [thresholdValue, setThresholdValue] = useState<string>(
    rule?.thresholdValue !== undefined ? String(rule?.thresholdValue) : '85'
  );
  const [thresholdUpperValue, setThresholdUpperValue] = useState<string>(
    rule?.thresholdUpperValue !== undefined ? String(rule?.thresholdUpperValue) : '120'
  );
  const [unit, setUnit] = useState(rule?.unit || '°C');
  const [delaySeconds, setDelaySeconds] = useState(rule?.delaySeconds ?? 0);

  // Role Configuration
  const [targetRoles, setTargetRoles] = useState<UserRole[]>(
    rule?.targetRoles || ['operator', 'engineer', 'admin']
  );
  const [escalationRole, setEscalationRole] = useState<UserRole>(rule?.escalationRole || 'admin');
  const [escalationTimeoutMinutes, setEscalationTimeoutMinutes] = useState(
    rule?.escalationTimeoutMinutes ?? 5
  );
  const [autoResolveOnNormal, setAutoResolveOnNormal] = useState(
    rule?.autoResolveOnNormal ?? true
  );

  // Actions
  const [inAppNotification, setInAppNotification] = useState(rule?.actions.inAppNotification ?? true);
  const [audioChime, setAudioChime] = useState(rule?.actions.audioChime ?? true);
  const [mqttPublishOnTrigger, setMqttPublishOnTrigger] = useState(
    rule?.actions.mqttPublishOnTrigger ?? true
  );
  const [mqttAlarmTopic, setMqttAlarmTopic] = useState(rule?.actions.mqttAlarmTopic || 'alarms/plant/critical');
  const [emailWebhook, setEmailWebhook] = useState(rule?.actions.emailWebhook ?? false);
  const [webhookUrl, setWebhookUrl] = useState(
    rule?.actions.webhookUrl || 'https://alerts.plant.internal/webhook'
  );

  const [validationError, setValidationError] = useState<string | null>(null);

  const toggleRole = (r: UserRole) => {
    setTargetRoles((prev) => {
      if (prev.includes(r)) {
        if (prev.length === 1) return prev; // At least one role required
        return prev.filter((item) => item !== r);
      } else {
        return [...prev, r];
      }
    });
  };

  const handleSave = () => {
    if (!name.trim()) {
      setValidationError('Rule name is required.');
      return;
    }
    if (!topic.trim()) {
      setValidationError('Target topic path is required.');
      return;
    }
    if (!metricField.trim()) {
      setValidationError('Metric field is required.');
      return;
    }
    if (targetRoles.length === 0) {
      setValidationError('At least one target role must be selected.');
      return;
    }

    const parsedThresh =
      thresholdValue === 'true'
        ? true
        : thresholdValue === 'false'
        ? false
        : !isNaN(Number(thresholdValue))
        ? Number(thresholdValue)
        : thresholdValue;

    const payload = {
      name: name.trim(),
      description: description.trim(),
      enabled: rule ? rule.enabled : true,
      severity,
      category,
      topic: topic.trim(),
      metricField: metricField.trim(),
      condition,
      thresholdValue: parsedThresh,
      thresholdUpperValue: condition === 'RANGE_OUTSIDE' ? Number(thresholdUpperValue) : undefined,
      unit: unit.trim(),
      delaySeconds: Number(delaySeconds) || 0,
      targetRoles,
      escalationRole,
      escalationTimeoutMinutes: Number(escalationTimeoutMinutes) || 5,
      autoResolveOnNormal,
      actions: {
        inAppNotification,
        audioChime,
        mqttPublishOnTrigger,
        mqttAlarmTopic: mqttPublishOnTrigger ? mqttAlarmTopic.trim() : undefined,
        emailWebhook,
        webhookUrl: emailWebhook ? webhookUrl.trim() : undefined,
      },
    };

    if (rule) {
      updateRule(rule.id, payload);
    } else {
      createRule(payload);
    }

    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/40 dark:bg-black/80 backdrop-blur-sm flex items-center justify-center p-3 sm:p-4 overflow-y-auto">
      <div className="bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] rounded-xl max-w-2xl w-full my-auto overflow-hidden flex flex-col max-h-[92vh] shadow-2xl font-sans text-xs">
        {/* Header */}
        <div className="p-3 sm:p-4 bg-white dark:bg-[#111114] border-b border-[#E2E8F0] dark:border-[#1E293B] flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-amber-50 dark:bg-[#FFC107]/10 border border-amber-200 dark:border-[#FFC107]/30 flex items-center justify-center text-amber-600 dark:text-[#FFC107]">
              <Sliders className="w-4 h-4" />
            </div>
            <div>
              <h2 className="font-display font-bold text-sm text-[#0F172A] dark:text-[#F8FAFC] text-balance">
                {rule ? 'Edit Alert Rule' : 'Create New Alert Rule'}
              </h2>
              <p className="text-[10px] text-[#64748B] dark:text-[#94A3B8] text-pretty">
                Configure real-time threshold conditions, role targeting, and dispatch channels.
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#E2E8F0] dark:border-[#1E293B] text-[#64748B] hover:text-[#0F172A] dark:hover:text-[#F8FAFC] cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Form Body */}
        <div className="p-4 overflow-y-auto space-y-4 flex-1 scrollbar-thin scrollbar-thumb-slate-300 dark:scrollbar-thumb-[#1E293B]">
          {validationError && (
            <div className="p-2.5 rounded-lg bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800 text-rose-700 dark:text-rose-300 text-[11px] flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 shrink-0" />
              <span>{validationError}</span>
            </div>
          )}

          {/* Section 1: Identity & Classification */}
          <div className="space-y-3 p-3 rounded-lg bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#E2E8F0] dark:border-[#1E293B]">
            <div className="text-[11px] font-mono font-bold text-amber-700 dark:text-[#FFC107] uppercase tracking-wider flex items-center gap-1.5">
              <span>1. Classification &amp; Identity</span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="block text-[11px] text-[#64748B] dark:text-[#94A3B8] mb-1 font-medium">
                  Rule Name *
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Reactor 1 Temperature High-High"
                  className="w-full bg-white dark:bg-[#111114] border border-[#CBD5E1] dark:border-[#1E293B] rounded-md px-2.5 py-1.5 text-xs text-[#0F172A] dark:text-[#F8FAFC] focus:outline-none focus:border-amber-500 dark:focus:border-[#FFC107]"
                />
              </div>

              <div>
                <label className="block text-[11px] text-[#64748B] dark:text-[#94A3B8] mb-1 font-medium">
                  Alarm Category
                </label>
                <select
                  value={category}
                  onChange={(e) => setCategory(e.target.value as AlarmCategory)}
                  className="w-full bg-white dark:bg-[#111114] border border-[#CBD5E1] dark:border-[#1E293B] rounded-md px-2.5 py-1.5 text-xs text-[#0F172A] dark:text-[#F8FAFC] focus:outline-none focus:border-amber-500 dark:focus:border-[#FFC107] cursor-pointer"
                >
                  {CATEGORIES.map((cat) => (
                    <option key={cat} value={cat}>
                      {cat}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="block text-[11px] text-[#64748B] dark:text-[#94A3B8] mb-1 font-medium">
                  Severity Level
                </label>
                <div className="grid grid-cols-4 gap-1">
                  {SEVERITIES.map((sev) => (
                    <button
                      key={sev}
                      type="button"
                      onClick={() => setSeverity(sev)}
                      className={`py-1.5 text-[10px] font-mono font-bold rounded border transition-all cursor-pointer ${
                        severity === sev
                          ? sev === 'CRITICAL'
                            ? 'bg-rose-500 text-black border-rose-500'
                            : sev === 'HIGH'
                            ? 'bg-amber-500 text-black border-amber-500'
                            : sev === 'WARNING'
                            ? 'bg-yellow-400 text-black border-yellow-400'
                            : 'bg-sky-500 text-black border-sky-500'
                          : 'bg-white dark:bg-[#111114] border-[#CBD5E1] dark:border-[#1E293B] text-[#64748B] dark:text-[#94A3B8]'
                      }`}
                    >
                      {sev}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="block text-[11px] text-[#64748B] dark:text-[#94A3B8] mb-1 font-medium">
                  Description / Context
                </label>
                <input
                  type="text"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Operational trigger instructions..."
                  className="w-full bg-white dark:bg-[#111114] border border-[#CBD5E1] dark:border-[#1E293B] rounded-md px-2.5 py-1.5 text-xs text-[#0F172A] dark:text-[#F8FAFC] focus:outline-none focus:border-amber-500 dark:focus:border-[#FFC107]"
                />
              </div>
            </div>
          </div>

          {/* Section 2: Metric Condition & Thresholds */}
          <div className="space-y-3 p-3 rounded-lg bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#E2E8F0] dark:border-[#1E293B]">
            <div className="text-[11px] font-mono font-bold text-amber-700 dark:text-[#FFC107] uppercase tracking-wider flex items-center gap-1.5">
              <span>2. Metric Threshold &amp; Conditions</span>
            </div>

            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="text-[11px] text-[#64748B] dark:text-[#94A3B8] font-medium">
                  Target Topic (ISA-95 or Sparkplug) *
                </label>
                <span className="text-[10px] text-[#64748B] font-mono">Use * for global wildcard</span>
              </div>
              <input
                type="text"
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                placeholder="e.g. CovestroAG/Dormagen/Polyurethane/Reactor_01/temperature"
                className="w-full bg-white dark:bg-[#111114] border border-[#CBD5E1] dark:border-[#1E293B] rounded-md px-2.5 py-1.5 text-xs text-[#0F172A] dark:text-[#F8FAFC] font-mono focus:outline-none focus:border-amber-500 dark:focus:border-[#FFC107]"
              />
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
              <div>
                <label className="block text-[11px] text-[#64748B] dark:text-[#94A3B8] mb-1 font-medium">
                  Metric Field / Key *
                </label>
                <input
                  type="text"
                  value={metricField}
                  onChange={(e) => setMetricField(e.target.value)}
                  placeholder="e.g. temp_celsius, pressure_bar"
                  className="w-full bg-white dark:bg-[#111114] border border-[#CBD5E1] dark:border-[#1E293B] rounded-md px-2.5 py-1.5 text-xs text-[#0F172A] dark:text-[#F8FAFC] font-mono focus:outline-none focus:border-amber-500 dark:focus:border-[#FFC107]"
                />
              </div>

              <div>
                <label className="block text-[11px] text-[#64748B] dark:text-[#94A3B8] mb-1 font-medium">
                  Condition Operator
                </label>
                <select
                  value={condition}
                  onChange={(e) => setCondition(e.target.value as AlarmConditionType)}
                  className="w-full bg-white dark:bg-[#111114] border border-[#CBD5E1] dark:border-[#1E293B] rounded-md px-2.5 py-1.5 text-xs text-[#0F172A] dark:text-[#F8FAFC] font-mono focus:outline-none focus:border-amber-500 dark:focus:border-[#FFC107] cursor-pointer"
                >
                  {CONDITIONS.map((cond) => (
                    <option key={cond.value} value={cond.value}>
                      {cond.label}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-[11px] text-[#64748B] dark:text-[#94A3B8] mb-1 font-medium">
                  Threshold Value *
                </label>
                <div className="flex items-center gap-1.5">
                  <input
                    type="text"
                    value={thresholdValue}
                    onChange={(e) => setThresholdValue(e.target.value)}
                    placeholder="e.g. 85.0"
                    className="flex-1 bg-white dark:bg-[#111114] border border-[#CBD5E1] dark:border-[#1E293B] rounded-md px-2.5 py-1.5 text-xs text-[#0F172A] dark:text-[#F8FAFC] font-mono focus:outline-none focus:border-amber-500 dark:focus:border-[#FFC107]"
                  />
                  <input
                    type="text"
                    value={unit}
                    onChange={(e) => setUnit(e.target.value)}
                    placeholder="Unit"
                    className="w-14 bg-white dark:bg-[#111114] border border-[#CBD5E1] dark:border-[#1E293B] rounded-md px-2 py-1.5 text-xs text-amber-700 dark:text-[#FFC107] font-mono text-center focus:outline-none focus:border-amber-500 dark:focus:border-[#FFC107]"
                  />
                </div>
              </div>
            </div>

            {condition === 'RANGE_OUTSIDE' && (
              <div>
                <label className="block text-[11px] text-[#64748B] dark:text-[#94A3B8] mb-1 font-medium">
                  Upper Threshold Limit
                </label>
                <input
                  type="number"
                  value={thresholdUpperValue}
                  onChange={(e) => setThresholdUpperValue(e.target.value)}
                  placeholder="e.g. 120.0"
                  className="w-full bg-white dark:bg-[#111114] border border-[#CBD5E1] dark:border-[#1E293B] rounded-md px-2.5 py-1.5 text-xs text-[#0F172A] dark:text-[#F8FAFC] font-mono focus:outline-none focus:border-amber-500 dark:focus:border-[#FFC107]"
                />
              </div>
            )}
          </div>

          {/* Section 3: ROLE-BASED TRIGGERING & ROUTING */}
          <div className="space-y-3 p-3 rounded-lg bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#E2E8F0] dark:border-[#1E293B]">
            <div className="text-[11px] font-mono font-bold text-amber-700 dark:text-[#FFC107] uppercase tracking-wider flex items-center justify-between">
              <span>3. Role-Based Notification Triggering</span>
              <span className="text-[9px] text-[#64748B] dark:text-[#94A3B8] lowercase font-normal">
                {targetRoles.length} roles selected
              </span>
            </div>

            <p className="text-[11px] text-[#64748B] dark:text-[#94A3B8]">
              Select which predefined roles will receive and be triggered by this incident:
            </p>

            {/* Pre-defined Roles Selector */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {PREDEFINED_ROLES.map((r) => {
                const roleCfg = ROLE_CONFIGS[r] || ROLE_CONFIGS.viewer;
                const isSelected = targetRoles.includes(r);

                return (
                  <div
                    key={r}
                    onClick={() => toggleRole(r)}
                    className={`p-2.5 rounded-lg border flex items-center justify-between cursor-pointer transition-all ${
                      isSelected
                        ? 'bg-amber-50 dark:bg-[#1E293B] border-amber-500 dark:border-[#FFC107] text-[#0F172A] dark:text-[#F8FAFC]'
                        : 'bg-white dark:bg-[#111114] border-[#E2E8F0] dark:border-[#1E293B] text-[#64748B] hover:border-[#94A3B8] dark:hover:border-[#334155]'
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <div
                        className={`w-4 h-4 rounded border flex items-center justify-center ${
                          isSelected ? 'bg-amber-500 dark:bg-[#FFC107] border-amber-500 dark:border-[#FFC107] text-black' : 'border-[#94A3B8] dark:border-[#64748B]'
                        }`}
                      >
                        {isSelected && <Check className="w-3 h-3 stroke-[3]" />}
                      </div>
                      <div>
                        <div className="font-bold text-xs">{roleCfg.label}</div>
                        <div className="text-[10px] text-[#64748B] dark:text-[#94A3B8]">{r}</div>
                      </div>
                    </div>

                    <span className={`text-[9px] px-1.5 py-0.5 rounded font-mono border ${roleCfg.badgeBg} ${roleCfg.badgeText} ${roleCfg.badgeBorder}`}>
                      {r.toUpperCase()}
                    </span>
                  </div>
                );
              })}
            </div>

            {/* Escalation Policy */}
            <div className="pt-2 border-t border-[#E2E8F0] dark:border-[#1E293B] grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="block text-[11px] text-[#64748B] dark:text-[#94A3B8] mb-1 font-medium">
                  Escalation Target Role (If Unacknowledged)
                </label>
                <select
                  value={escalationRole}
                  onChange={(e) => setEscalationRole(e.target.value as UserRole)}
                  className="w-full bg-white dark:bg-[#111114] border border-[#CBD5E1] dark:border-[#1E293B] rounded-md px-2.5 py-1.5 text-xs text-[#0F172A] dark:text-[#F8FAFC] font-mono focus:outline-none focus:border-amber-500 dark:focus:border-[#FFC107] cursor-pointer"
                >
                  {PREDEFINED_ROLES.map((r) => (
                    <option key={r} value={r}>
                      {ROLE_CONFIGS[r]?.label || r}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-[11px] text-[#64748B] dark:text-[#94A3B8] mb-1 font-medium">
                  Escalation Timeout
                </label>
                <div className="flex items-center gap-1.5">
                  <input
                    type="number"
                    value={escalationTimeoutMinutes}
                    onChange={(e) => setEscalationTimeoutMinutes(Number(e.target.value))}
                    min={1}
                    max={120}
                    className="flex-1 bg-white dark:bg-[#111114] border border-[#CBD5E1] dark:border-[#1E293B] rounded-md px-2.5 py-1.5 text-xs text-[#0F172A] dark:text-[#F8FAFC] font-mono focus:outline-none focus:border-amber-500 dark:focus:border-[#FFC107]"
                  />
                  <span className="text-[#64748B] font-mono text-[11px]">Minutes</span>
                </div>
              </div>
            </div>
          </div>

          {/* Section 4: Action Outputs */}
          <div className="space-y-3 p-3 rounded-lg bg-[#F8FAFC] dark:bg-[#0B0B0C] border border-[#E2E8F0] dark:border-[#1E293B]">
            <div className="text-[11px] font-mono font-bold text-amber-700 dark:text-[#FFC107] uppercase tracking-wider">
              4. Dispatch Actions &amp; Notifications
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
              <label className="flex items-center gap-2 p-2 rounded bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] cursor-pointer">
                <input
                  type="checkbox"
                  checked={inAppNotification}
                  onChange={(e) => setInAppNotification(e.target.checked)}
                  className="accent-[#FFC107]"
                />
                <Bell className="w-3.5 h-3.5 text-amber-600 dark:text-[#FFC107]" />
                <span className="text-[11px] text-[#0F172A] dark:text-[#F8FAFC]">In-App Incident Banner</span>
              </label>

              <label className="flex items-center gap-2 p-2 rounded bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] cursor-pointer">
                <input
                  type="checkbox"
                  checked={audioChime}
                  onChange={(e) => setAudioChime(e.target.checked)}
                  className="accent-[#FFC107]"
                />
                <Volume2 className="w-3.5 h-3.5 text-rose-400" />
                <span className="text-[11px] text-[#0F172A] dark:text-[#F8FAFC]">Industrial Audio Chime</span>
              </label>

              <label className="flex items-center gap-2 p-2 rounded bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] cursor-pointer">
                <input
                  type="checkbox"
                  checked={mqttPublishOnTrigger}
                  onChange={(e) => setMqttPublishOnTrigger(e.target.checked)}
                  className="accent-[#FFC107]"
                />
                <Send className="w-3.5 h-3.5 text-emerald-400" />
                <span className="text-[11px] text-[#0F172A] dark:text-[#F8FAFC]">Publish to MQTT Alarm Topic</span>
              </label>

              <label className="flex items-center gap-2 p-2 rounded bg-white dark:bg-[#111114] border border-[#E2E8F0] dark:border-[#1E293B] cursor-pointer">
                <input
                  type="checkbox"
                  checked={autoResolveOnNormal}
                  onChange={(e) => setAutoResolveOnNormal(e.target.checked)}
                  className="accent-[#FFC107]"
                />
                <Check className="w-3.5 h-3.5 text-sky-400" />
                <span className="text-[11px] text-[#0F172A] dark:text-[#F8FAFC]">Auto-Resolve on Normal Range</span>
              </label>
            </div>

            {mqttPublishOnTrigger && (
              <div>
                <label className="block text-[11px] text-[#64748B] dark:text-[#94A3B8] mb-1 font-medium">
                  MQTT Alarm Publication Topic
                </label>
                <input
                  type="text"
                  value={mqttAlarmTopic}
                  onChange={(e) => setMqttAlarmTopic(e.target.value)}
                  placeholder="alarms/plant/incident"
                  className="w-full bg-white dark:bg-[#111114] border border-[#CBD5E1] dark:border-[#1E293B] rounded-md px-2.5 py-1.5 text-xs text-[#0F172A] dark:text-[#F8FAFC] font-mono focus:outline-none focus:border-amber-500 dark:focus:border-[#FFC107]"
                />
              </div>
            )}
          </div>
        </div>

        {/* Footer Actions */}
        <div className="p-3 sm:p-4 bg-white dark:bg-[#111114] border-t border-[#E2E8F0] dark:border-[#1E293B] flex items-center justify-between shrink-0">
          <button
            type="button"
            onClick={onClose}
            className="px-3.5 py-2 rounded-lg border border-[#CBD5E1] dark:border-[#1E293B] text-[#64748B] dark:text-[#94A3B8] hover:text-[#0F172A] dark:hover:text-[#F8FAFC] text-xs font-mono transition-colors cursor-pointer"
          >
            Cancel
          </button>

          <button
            type="button"
            onClick={handleSave}
            className="px-5 py-2 rounded-lg bg-amber-500 dark:bg-[#FFC107] hover:bg-amber-400 dark:hover:bg-[#FFB300] text-[#0B0B0C] font-bold text-xs font-mono transition-colors cursor-pointer shadow-sm"
          >
            {rule ? 'Update Alert Rule' : 'Create Alert Rule'}
          </button>
        </div>
      </div>
    </div>
  );
};

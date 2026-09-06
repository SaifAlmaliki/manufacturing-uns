import React, { useEffect, useMemo, useState } from 'react';
import {
  X,
  AlertTriangle,
  Sliders,
  Bell,
  Volume2,
  Send,
  Check,
  Radio,
} from 'lucide-react';
import {
  AlertRule,
  AlarmSeverity,
  AlarmCategory,
  AlarmConditionType,
} from '../../types/alarm';
import { UserRole, ROLE_CONFIGS } from '../../types/rbac';
import { useAlarms } from '../../context/AlarmContext';
import { unsGraphQLClient } from '../../services/graphql/client';
import type { GraphqlSubscribedSignal } from '../../services/graphql/types';
import { filterSubscribedSignals } from '../../lib/connectivity/signal-filters';
import {
  conditionsForDataType,
  defaultsFromSignal,
  SIGNAL_METRIC_FIELD,
  signalRowKey,
} from '../../lib/alarms/from-signal';
import {
  BtnGhost,
  BtnPrimary,
  BtnSecondary,
  ConsoleInput,
  ConsoleSelect,
  SegmentTabs,
  consoleTokens,
} from '../ui/console-ui';

interface AlertRuleEditorModalProps {
  rule: AlertRule | null;
  onClose: () => void;
}

type EditorSection = 'signal' | 'rule' | 'roles' | 'actions';

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

const PREDEFINED_ROLES: UserRole[] = ['operator', 'engineer', 'admin', 'auditor', 'viewer'];

const severityActiveClass: Record<AlarmSeverity, string> = {
  CRITICAL: 'bg-red-500/20 text-red-300 border-red-500/50',
  HIGH: 'bg-[#FF7A00]/20 text-[#FF7A00] border-[#FF7A00]/50',
  WARNING: 'bg-yellow-500/20 text-yellow-300 border-yellow-500/50',
  INFO: 'bg-sky-500/20 text-sky-300 border-sky-500/50',
};

function FieldLabel({ children, required }: { children: React.ReactNode; required?: boolean }) {
  return (
    <label className={`${consoleTokens.label} mb-1 block`}>
      {children}
      {required ? ' *' : ''}
    </label>
  );
}

export const AlertRuleEditorModal: React.FC<AlertRuleEditorModalProps> = ({ rule, onClose }) => {
  const { createRule, updateRule, canPersistRules, rulesError } = useAlarms();

  const [section, setSection] = useState<EditorSection>('signal');
  const [name, setName] = useState(rule?.name || '');
  const [description, setDescription] = useState(rule?.description || '');
  const [category, setCategory] = useState<AlarmCategory>(rule?.category || 'THRESHOLD');
  const [severity, setSeverity] = useState<AlarmSeverity>(rule?.severity || 'HIGH');
  const [topic, setTopic] = useState(rule?.topic || '');
  const [metricField, setMetricField] = useState(rule?.metricField || SIGNAL_METRIC_FIELD);
  const [condition, setCondition] = useState<AlarmConditionType>(rule?.condition || 'GREATER_THAN');
  const [thresholdValue, setThresholdValue] = useState<string>(
    rule?.thresholdValue !== undefined ? String(rule?.thresholdValue) : '',
  );
  const [thresholdUpperValue, setThresholdUpperValue] = useState<string>(
    rule?.thresholdUpperValue !== undefined ? String(rule?.thresholdUpperValue) : '',
  );
  const [unit, setUnit] = useState(rule?.unit || '');
  const [delaySeconds, setDelaySeconds] = useState(rule?.delaySeconds ?? 0);

  const [targetRoles, setTargetRoles] = useState<UserRole[]>(
    rule?.targetRoles || ['operator', 'engineer', 'admin'],
  );
  const [escalationRole, setEscalationRole] = useState<UserRole>(rule?.escalationRole || 'admin');
  const [escalationTimeoutMinutes, setEscalationTimeoutMinutes] = useState(
    rule?.escalationTimeoutMinutes ?? 5,
  );
  const [autoResolveOnNormal, setAutoResolveOnNormal] = useState(rule?.autoResolveOnNormal ?? true);

  const [inAppNotification, setInAppNotification] = useState(rule?.actions.inAppNotification ?? true);
  const [audioChime, setAudioChime] = useState(rule?.actions.audioChime ?? true);
  const [mqttPublishOnTrigger, setMqttPublishOnTrigger] = useState(
    rule?.actions.mqttPublishOnTrigger ?? false,
  );
  const [mqttAlarmTopic, setMqttAlarmTopic] = useState(rule?.actions.mqttAlarmTopic || '');
  const [emailWebhook, setEmailWebhook] = useState(rule?.actions.emailWebhook ?? false);
  const [webhookUrl, setWebhookUrl] = useState(rule?.actions.webhookUrl || '');

  const [signals, setSignals] = useState<GraphqlSubscribedSignal[]>([]);
  const [signalsLoading, setSignalsLoading] = useState(true);
  const [signalsError, setSignalsError] = useState<string | null>(null);
  const [signalSearch, setSignalSearch] = useState('');
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  const [validationError, setValidationError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      setSignalsLoading(true);
      setSignalsError(null);
      try {
        const rows = await unsGraphQLClient.getSubscribedSignals();
        if (cancelled) return;
        setSignals(rows);
        if (rule?.topic) {
          const match = rows.find((row) => row.mqttTopic === rule.topic);
          if (match) setSelectedKey(signalRowKey(match));
        }
      } catch (error) {
        if (!cancelled) {
          setSignals([]);
          setSignalsError(
            error instanceof Error ? error.message : 'Subscribed signals could not be loaded.',
          );
        }
      } finally {
        if (!cancelled) setSignalsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [rule?.topic]);

  const filteredSignals = useMemo(
    () => filterSubscribedSignals(signals, { search: signalSearch }),
    [signals, signalSearch],
  );
  const selectedSignal = signals.find((row) => signalRowKey(row) === selectedKey) ?? null;
  const conditionOptions = useMemo(() => {
    const options = conditionsForDataType(selectedSignal?.dataType);
    if (options.some((option) => option.value === condition)) return options;
    return [{ label: condition.replaceAll('_', ' '), value: condition }, ...options];
  }, [selectedSignal, condition]);

  const applySignal = (row: GraphqlSubscribedSignal) => {
    const defaults = defaultsFromSignal(row);
    setSelectedKey(signalRowKey(row));
    setTopic(defaults.topic);
    setMetricField(defaults.metricField);
    if (defaults.unit) setUnit(defaults.unit);
    if (!rule) {
      setName(defaults.suggestedName);
      setCategory(defaults.category);
      setCondition(defaults.condition);
    }
    setValidationError(null);
  };

  const toggleRole = (r: UserRole) => {
    setTargetRoles((prev) => {
      if (prev.includes(r)) {
        if (prev.length === 1) return prev;
        return prev.filter((item) => item !== r);
      }
      return [...prev, r];
    });
  };

  const goNext = () => {
    if (section === 'signal') {
      if (!topic.trim()) {
        setValidationError('Select a signal first.');
        return;
      }
      setValidationError(null);
      setSection('rule');
      return;
    }
    if (section === 'rule') setSection('roles');
    else if (section === 'roles') setSection('actions');
  };

  const handleSave = async () => {
    if (!canPersistRules) {
      setValidationError(
        rulesError ??
          'The platform database is offline. Start GraphQL on port 8000 before saving alert rules.',
      );
      return;
    }
    if (!topic.trim()) {
      setValidationError('Select a signal first.');
      setSection('signal');
      return;
    }
    if (!metricField.trim()) {
      setValidationError('Metric field is required.');
      setSection('rule');
      return;
    }
    if (!name.trim()) {
      setValidationError('Rule name is required.');
      setSection('rule');
      return;
    }
    if (targetRoles.length === 0) {
      setValidationError('At least one target role must be selected.');
      setSection('roles');
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

    setIsSaving(true);
    setValidationError(null);
    try {
      if (rule) {
        await updateRule(rule.id, payload);
      } else {
        await createRule(payload);
      }
      onClose();
    } catch (error) {
      setValidationError(error instanceof Error ? error.message : 'Alert rule could not be saved.');
    } finally {
      setIsSaving(false);
    }
  };

  const sectionTabs = [
    { id: 'signal', label: 'Signal' },
    { id: 'rule', label: 'Rule' },
    { id: 'roles', label: 'Roles', badge: targetRoles.length },
    { id: 'actions', label: 'Actions' },
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-3 backdrop-blur-sm sm:p-4">
      <div
        className={`${consoleTokens.card} flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden shadow-2xl`}
        role="dialog"
        aria-labelledby="alert-rule-editor-title"
      >
        <div className="flex shrink-0 items-center justify-between border-b border-zinc-800 px-4 py-3">
          <div className="flex items-center gap-2.5">
            <div className="flex size-8 items-center justify-center rounded-lg bg-[#FF7A00]/15">
              <Sliders className="size-4 text-[#FF7A00]" />
            </div>
            <h2 id="alert-rule-editor-title" className="text-sm font-semibold text-white">
              {rule ? 'Edit alert rule' : 'New alert rule'}
            </h2>
          </div>
          <BtnGhost onClick={onClose} className="px-2 py-1.5" aria-label="Close">
            <X className="size-4" />
          </BtnGhost>
        </div>

        <div className="shrink-0 border-b border-zinc-800 px-4 py-2">
          <SegmentTabs
            tabs={sectionTabs}
            active={section}
            onChange={(id) => setSection(id as EditorSection)}
          />
        </div>

        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3">
          {validationError && (
            <div className="flex items-center gap-2 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              <AlertTriangle className="size-4 shrink-0" />
              <span>{validationError}</span>
            </div>
          )}

          {section === 'signal' && (
            <div className="space-y-3">
              <p className="text-xs text-zinc-500">
                Pick the subscribed signal this alert watches, then choose the condition on the Rule
                tab.
              </p>
              <ConsoleInput
                aria-label="Search signals"
                value={signalSearch}
                onChange={(e) => setSignalSearch(e.target.value)}
                placeholder="Search name, topic, server…"
              />
              {signalsError && (
                <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
                  {signalsError}
                </div>
              )}
              {signalsLoading ? (
                <div className="py-10 text-center text-sm text-zinc-500">Loading subscribed signals…</div>
              ) : filteredSignals.length === 0 ? (
                <div className="py-10 text-center text-sm text-zinc-500">
                  {signals.length === 0
                    ? 'No subscribed signals. Subscribe tags on Connectivity → Signals first.'
                    : 'No signals match this search.'}
                </div>
              ) : (
                <ul className="max-h-72 divide-y divide-zinc-800 overflow-y-auto rounded-lg border border-zinc-800">
                  {filteredSignals.map((row) => {
                    const isSelected = selectedKey === signalRowKey(row);
                    return (
                      <li key={signalRowKey(row)}>
                        <button
                          type="button"
                          aria-pressed={isSelected}
                          onClick={() => applySignal(row)}
                          className={`flex w-full items-start gap-2.5 px-3 py-2.5 text-left transition-colors ${
                            isSelected
                              ? 'bg-[#FF7A00]/10'
                              : 'hover:bg-zinc-800/40'
                          }`}
                        >
                          <Radio
                            className={`mt-0.5 size-3.5 shrink-0 ${
                              isSelected ? 'text-[#FF7A00]' : 'text-zinc-600'
                            }`}
                          />
                          <div className="min-w-0 flex-1">
                            <div className="text-sm font-medium text-white">{row.displayName}</div>
                            <div className="truncate font-mono text-[11px] text-zinc-500">
                              {row.mqttTopic}
                            </div>
                          </div>
                          <div className="shrink-0 text-right">
                            {row.unitOfMeasure ? (
                              <div className="font-mono text-[11px] text-zinc-400">{row.unitOfMeasure}</div>
                            ) : null}
                            <div className="text-[10px] uppercase text-zinc-600">{row.serverName}</div>
                          </div>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
              {topic ? (
                <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 px-3 py-2 text-xs text-zinc-300">
                  Watching{' '}
                  <span className="font-mono text-[#FF7A00]">{topic}</span>
                  {selectedSignal ? null : (
                    <span className="ml-2 text-zinc-500">
                      (path is not in the subscribed catalog)
                    </span>
                  )}
                </div>
              ) : null}
            </div>
          )}

          {section === 'rule' && (
            <div className="space-y-3">
              {topic ? (
                <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 px-3 py-2 text-xs text-zinc-400">
                  Signal{' '}
                  <span className="font-mono text-zinc-200">{topic}</span>
                </div>
              ) : (
                <p className="text-xs text-amber-300">Select a signal first — this rule needs a target.</p>
              )}
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="sm:col-span-2">
                  <FieldLabel required>Rule name</FieldLabel>
                  <ConsoleInput
                    aria-label="Rule name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Reactor 01 temperature high-high"
                  />
                </div>
                <div>
                  <FieldLabel>Category</FieldLabel>
                  <ConsoleSelect
                    value={category}
                    onChange={(e) => setCategory(e.target.value as AlarmCategory)}
                  >
                    {CATEGORIES.map((cat) => (
                      <option key={cat} value={cat}>
                        {cat}
                      </option>
                    ))}
                  </ConsoleSelect>
                </div>
                <div>
                  <FieldLabel>Description</FieldLabel>
                  <ConsoleInput
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="Optional context for operators"
                  />
                </div>
                <div className="sm:col-span-2">
                  <FieldLabel>Severity</FieldLabel>
                  <div className="flex flex-wrap gap-1.5">
                    {SEVERITIES.map((sev) => (
                      <button
                        key={sev}
                        type="button"
                        onClick={() => setSeverity(sev)}
                        className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
                          severity === sev
                            ? severityActiveClass[sev]
                            : 'border-zinc-800 bg-zinc-900/60 text-zinc-400 hover:text-zinc-200'
                        }`}
                      >
                        {sev}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
              <div className="grid gap-3 border-t border-zinc-800 pt-3 sm:grid-cols-2 lg:grid-cols-4">
                <div>
                  <FieldLabel>Condition</FieldLabel>
                  <ConsoleSelect
                    aria-label="Condition"
                    value={condition}
                    onChange={(e) => setCondition(e.target.value as AlarmConditionType)}
                    className="font-mono text-xs"
                  >
                    {conditionOptions.map((cond) => (
                      <option key={cond.value} value={cond.value}>
                        {cond.label}
                      </option>
                    ))}
                  </ConsoleSelect>
                </div>
                <div>
                  <FieldLabel required>Threshold</FieldLabel>
                  <ConsoleInput
                    aria-label="Threshold"
                    value={thresholdValue}
                    onChange={(e) => setThresholdValue(e.target.value)}
                    placeholder="85"
                    className="font-mono"
                  />
                </div>
                <div>
                  <FieldLabel>Unit</FieldLabel>
                  <ConsoleInput
                    value={unit}
                    onChange={(e) => setUnit(e.target.value)}
                    placeholder="°C"
                    className="font-mono"
                  />
                </div>
                <div>
                  <FieldLabel>Delay (seconds)</FieldLabel>
                  <ConsoleInput
                    type="number"
                    min={0}
                    value={delaySeconds}
                    onChange={(e) => setDelaySeconds(Number(e.target.value))}
                    className="font-mono"
                  />
                </div>
              </div>
              {condition === 'RANGE_OUTSIDE' && (
                <div className="max-w-xs">
                  <FieldLabel>Upper limit</FieldLabel>
                  <ConsoleInput
                    type="number"
                    value={thresholdUpperValue}
                    onChange={(e) => setThresholdUpperValue(e.target.value)}
                    className="font-mono"
                  />
                </div>
              )}
            </div>
          )}

          {section === 'roles' && (
            <div className="space-y-3">
              <p className="text-xs text-zinc-500">
                Roles that receive this alarm when the signal breaches the rule.
              </p>
              <div className="flex flex-wrap gap-2">
                {PREDEFINED_ROLES.map((r) => {
                  const roleCfg = ROLE_CONFIGS[r] || ROLE_CONFIGS.viewer;
                  const isSelected = targetRoles.includes(r);
                  return (
                    <button
                      key={r}
                      type="button"
                      onClick={() => toggleRole(r)}
                      className={`inline-flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs transition-colors ${
                        isSelected
                          ? 'border-[#FF7A00]/50 bg-[#FF7A00]/10 text-white'
                          : 'border-zinc-800 bg-zinc-900/50 text-zinc-400 hover:border-zinc-700 hover:text-zinc-200'
                      }`}
                    >
                      <span
                        className={`flex size-4 items-center justify-center rounded border ${
                          isSelected
                            ? 'border-[#FF7A00] bg-[#FF7A00] text-black'
                            : 'border-zinc-600 bg-transparent'
                        }`}
                      >
                        {isSelected && <Check className="size-2.5 stroke-[3]" />}
                      </span>
                      <span className="font-medium">{roleCfg.label}</span>
                      <span className="text-[10px] uppercase text-zinc-500">{r}</span>
                    </button>
                  );
                })}
              </div>
              <div className="grid gap-3 border-t border-zinc-800 pt-3 sm:grid-cols-2">
                <div>
                  <FieldLabel>Escalation role</FieldLabel>
                  <ConsoleSelect
                    value={escalationRole}
                    onChange={(e) => setEscalationRole(e.target.value as UserRole)}
                  >
                    {PREDEFINED_ROLES.map((r) => (
                      <option key={r} value={r}>
                        {ROLE_CONFIGS[r]?.label || r}
                      </option>
                    ))}
                  </ConsoleSelect>
                </div>
                <div>
                  <FieldLabel>Escalation timeout (min)</FieldLabel>
                  <ConsoleInput
                    type="number"
                    min={1}
                    max={120}
                    value={escalationTimeoutMinutes}
                    onChange={(e) => setEscalationTimeoutMinutes(Number(e.target.value))}
                    className="font-mono"
                  />
                </div>
              </div>
            </div>
          )}

          {section === 'actions' && (
            <div className="space-y-3">
              <div className="grid gap-2 sm:grid-cols-2">
                {[
                  { checked: inAppNotification, set: setInAppNotification, icon: Bell, label: 'In-app banner' },
                  { checked: audioChime, set: setAudioChime, icon: Volume2, label: 'Audio chime' },
                  { checked: mqttPublishOnTrigger, set: setMqttPublishOnTrigger, icon: Send, label: 'MQTT publish' },
                  { checked: autoResolveOnNormal, set: setAutoResolveOnNormal, icon: Check, label: 'Auto-resolve' },
                ].map(({ checked, set, icon: Icon, label }) => (
                  <label
                    key={label}
                    className="flex cursor-pointer items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-900/50 px-3 py-2 text-xs text-zinc-300"
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(e) => set(e.target.checked)}
                      className="accent-[#FF7A00]"
                    />
                    <Icon className="size-3.5 shrink-0 text-[#FF7A00]" />
                    {label}
                  </label>
                ))}
              </div>
              {mqttPublishOnTrigger && (
                <div>
                  <FieldLabel>MQTT alarm topic</FieldLabel>
                  <ConsoleInput
                    value={mqttAlarmTopic}
                    onChange={(e) => setMqttAlarmTopic(e.target.value)}
                    placeholder="alarms/plant/incident"
                    className="font-mono"
                  />
                </div>
              )}
              <label className="flex cursor-pointer items-center gap-2 text-xs text-zinc-400">
                <input
                  type="checkbox"
                  checked={emailWebhook}
                  onChange={(e) => setEmailWebhook(e.target.checked)}
                  className="accent-[#FF7A00]"
                />
                Webhook notification
              </label>
              {emailWebhook && (
                <ConsoleInput
                  value={webhookUrl}
                  onChange={(e) => setWebhookUrl(e.target.value)}
                  placeholder="https://…"
                  className="font-mono text-xs"
                />
              )}
            </div>
          )}
        </div>

        <div className="flex shrink-0 items-center justify-end gap-2 border-t border-zinc-800 px-4 py-3">
          <BtnSecondary onClick={onClose} className="px-3 py-1.5 text-xs">
            Cancel
          </BtnSecondary>
          {section !== 'actions' && (
            <BtnSecondary onClick={goNext} className="px-3 py-1.5 text-xs">
              Next
            </BtnSecondary>
          )}
          <BtnPrimary
            onClick={() => void handleSave()}
            disabled={isSaving || !canPersistRules}
            className="px-4 py-1.5 text-xs"
          >
            {isSaving ? 'Saving…' : rule ? 'Update rule' : 'Create rule'}
          </BtnPrimary>
        </div>
      </div>
    </div>
  );
};

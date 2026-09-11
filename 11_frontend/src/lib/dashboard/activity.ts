import type { MqttMessage } from '../../types/uns';

/** Twelve 5s bars — one minute, which is what the live MQTT buffer can actually fill. */
export const ACTIVITY_BUCKETS = 12;
export const ACTIVITY_BUCKET_MS = 5_000;
export const ACTIVITY_WINDOW_MS = ACTIVITY_BUCKETS * ACTIVITY_BUCKET_MS;

const NOISE_LEAF = new Set(['sim', 'heartbeat', 'state']);

export function isDashboardNoiseTopic(topic: string): boolean {
  const parts = topic.split('/').filter(Boolean);
  const last = (parts[parts.length - 1] ?? '').toLowerCase();
  return NOISE_LEAF.has(last);
}

export function formatTopicShort(topic: string): string {
  const parts = topic.split('/').filter(Boolean);
  return parts.length > 2 ? parts.slice(-2).join(' / ') : topic;
}

function scalarEventValue(raw: unknown): string | null {
  if (typeof raw === 'number' && Number.isFinite(raw)) {
    return String(Number(raw.toFixed(2)));
  }
  if (typeof raw === 'boolean') return raw ? 'true' : 'false';
  if (typeof raw === 'string') return raw;
  return null;
}

export function formatEventValue(payload: MqttMessage['payload']): string {
  const raw =
    payload && typeof payload === 'object' && !Array.isArray(payload) && 'value' in payload
      ? (payload as { value: unknown }).value
      : payload;
  const scalar = scalarEventValue(raw);
  if (scalar != null) return scalar;
  if (raw == null) return '—';
  try {
    return JSON.stringify(raw);
  } catch {
    return '—';
  }
}

/** Compact title for dashboard recent-event rows (topic + business metadata when present). */
export function formatRecentEventTitle(topic: string, payload: MqttMessage['payload']): string {
  const short = formatTopicShort(topic);
  if (payload && typeof payload === 'object' && !Array.isArray(payload)) {
    const record = payload as Record<string, unknown>;
    if (typeof record.source_application === 'string' && typeof record.payload_schema_id === 'string') {
      return `${short} · ${record.source_application}/${record.payload_schema_id}`;
    }
  }
  return short;
}

/** Full payload text for a recent-event row; wraps inside the card instead of overflowing. */
export function formatRecentEventBody(payload: MqttMessage['payload']): string {
  if (payload == null) return '—';
  if (typeof payload === 'string') return payload;
  if (typeof payload === 'number' || typeof payload === 'boolean') {
    return scalarEventValue(payload) ?? '—';
  }
  if (typeof payload === 'object' && !Array.isArray(payload) && 'value' in payload) {
    const inner = (payload as { value: unknown }).value;
    const scalar = scalarEventValue(inner);
    if (scalar != null) return scalar;
  }
  try {
    return JSON.stringify(payload);
  } catch {
    return '—';
  }
}

function isProcessMessage(msg: Pick<MqttMessage, 'topic'>): boolean {
  return !isDashboardNoiseTopic(msg.topic);
}

export function bucketMessageActivity(
  feed: Pick<MqttMessage, 'topic' | 'timestamp'>[],
  now = Date.now(),
  buckets = ACTIVITY_BUCKETS,
  bucketMs = ACTIVITY_BUCKET_MS,
): number[] {
  const counts = Array.from({ length: buckets }, () => 0);
  const windowMs = buckets * bucketMs;
  for (const msg of feed) {
    if (!isProcessMessage(msg)) continue;
    const age = now - Date.parse(msg.timestamp);
    if (!Number.isFinite(age) || age < 0 || age >= windowMs) continue;
    const fromNewest = Math.floor(age / bucketMs);
    counts[buckets - 1 - fromNewest] += 1;
  }
  return counts;
}

export function messagesInWindow(
  feed: Pick<MqttMessage, 'topic' | 'timestamp'>[],
  now = Date.now(),
  windowMs = ACTIVITY_WINDOW_MS,
): number {
  return feed.filter((msg) => {
    if (!isProcessMessage(msg)) return false;
    const age = now - Date.parse(msg.timestamp);
    return Number.isFinite(age) && age >= 0 && age < windowMs;
  }).length;
}

export function selectRecentEvents(feed: MqttMessage[], limit = 6): MqttMessage[] {
  const latest = new Map<string, MqttMessage>();
  for (const msg of feed) {
    if (!isProcessMessage(msg)) continue;
    const existing = latest.get(msg.topic);
    if (!existing || Date.parse(msg.timestamp) >= Date.parse(existing.timestamp)) {
      latest.set(msg.topic, msg);
    }
  }
  return [...latest.values()]
    .sort((a, b) => Date.parse(b.timestamp) - Date.parse(a.timestamp))
    .slice(0, limit);
}

export function lastMessageAgeMs(
  feed: Pick<MqttMessage, 'topic' | 'timestamp'>[],
  now = Date.now(),
): number | null {
  let newest: number | null = null;
  for (const msg of feed) {
    if (!isProcessMessage(msg)) continue;
    const ts = Date.parse(msg.timestamp);
    if (!Number.isFinite(ts)) continue;
    if (newest == null || ts > newest) newest = ts;
  }
  if (newest == null) return null;
  return Math.max(0, now - newest);
}

export function formatAge(ageMs: number | null): string {
  if (ageMs == null) return 'Quiet';
  if (ageMs < 1_000) return 'now';
  if (ageMs < 60_000) return `${Math.round(ageMs / 1_000)}s ago`;
  return `${Math.round(ageMs / 60_000)}m ago`;
}

/** 100% when the last process message is fresh; empty when the feed is quiet. */
export function freshnessPct(ageMs: number | null, decayMs = ACTIVITY_WINDOW_MS): number | null {
  if (ageMs == null) return null;
  return Math.max(0, Math.round(100 * (1 - Math.min(ageMs, decayMs) / decayMs)));
}

import { describe, expect, it } from 'vitest';
import type { MqttMessage } from '../../types/uns';
import {
  ACTIVITY_BUCKET_MS,
  ACTIVITY_BUCKETS,
  bucketMessageActivity,
  formatEventValue,
  formatTopicShort,
  isDashboardNoiseTopic,
  lastMessageAgeMs,
  messagesInWindow,
  selectRecentEvents,
} from './activity';

function msg(over: Partial<MqttMessage> & Pick<MqttMessage, 'topic' | 'timestamp'>): MqttMessage {
  return {
    id: over.id ?? over.topic,
    payload: over.payload ?? { value: 1 },
    ...over,
  };
}

describe('isDashboardNoiseTopic', () => {
  it('drops simulator heartbeat and edge/sim folders', () => {
    expect(isDashboardNoiseTopic('HalabjaWTP/edge/sim')).toBe(true);
    expect(isDashboardNoiseTopic('plant/line/sim')).toBe(true);
    expect(isDashboardNoiseTopic('plant/heartbeat')).toBe(true);
  });

  it('keeps process tags', () => {
    expect(isDashboardNoiseTopic('HalabjaWTP/P101/Current')).toBe(false);
    expect(isDashboardNoiseTopic('HalabjaWTP/AIT100/Value')).toBe(false);
  });
});

describe('bucketMessageActivity', () => {
  const now = Date.parse('2026-09-06T20:18:00.000Z');

  it('puts the newest messages in the rightmost bucket, not the leftmost', () => {
    const feed = [
      msg({ topic: 'a/Value', timestamp: new Date(now - 2_000).toISOString() }),
      msg({ topic: 'b/Value', timestamp: new Date(now - 2_000).toISOString() }),
      msg({ topic: 'c/Value', timestamp: new Date(now - 58_000).toISOString() }),
    ];
    const buckets = bucketMessageActivity(feed, now);
    expect(buckets).toHaveLength(ACTIVITY_BUCKETS);
    expect(buckets[ACTIVITY_BUCKETS - 1]).toBe(2);
    expect(buckets[0]).toBe(1);
    expect(buckets.slice(1, -1).every((n) => n === 0)).toBe(true);
  });

  it('ignores noise topics so the chart is not a firehose', () => {
    const feed = [
      msg({ topic: 'plant/edge/sim', timestamp: new Date(now - 1_000).toISOString() }),
      msg({ topic: 'plant/P101/Current', timestamp: new Date(now - 1_000).toISOString() }),
    ];
    expect(bucketMessageActivity(feed, now)[ACTIVITY_BUCKETS - 1]).toBe(1);
  });
});

describe('messagesInWindow', () => {
  it('counts only the last minute of process traffic', () => {
    const now = Date.parse('2026-09-06T20:18:00.000Z');
    const feed = [
      msg({ topic: 'a/Value', timestamp: new Date(now - 10_000).toISOString() }),
      msg({ topic: 'plant/edge/sim', timestamp: new Date(now - 10_000).toISOString() }),
      msg({ topic: 'b/Value', timestamp: new Date(now - 90_000).toISOString() }),
    ];
    expect(messagesInWindow(feed, now, 60_000)).toBe(1);
  });
});

describe('selectRecentEvents', () => {
  it('keeps the latest sample per topic and drops edge/sim', () => {
    const now = Date.parse('2026-09-06T20:18:00.000Z');
    const feed = [
      msg({
        id: 'new-p101',
        topic: 'HalabjaWTP/P101/Current',
        timestamp: new Date(now).toISOString(),
        payload: { value: 12.4 },
      }),
      msg({
        id: 'old-p101',
        topic: 'HalabjaWTP/P101/Current',
        timestamp: new Date(now - 5_000).toISOString(),
        payload: { value: 11 },
      }),
      msg({
        id: 'sim',
        topic: 'HalabjaWTP/edge/sim',
        timestamp: new Date(now).toISOString(),
      }),
      msg({
        id: 'ait',
        topic: 'HalabjaWTP/AIT100/Value',
        timestamp: new Date(now - 1_000).toISOString(),
        payload: { value: 7.1 },
      }),
    ];
    const events = selectRecentEvents(feed, 6);
    expect(events.map((e) => e.topic)).toEqual([
      'HalabjaWTP/P101/Current',
      'HalabjaWTP/AIT100/Value',
    ]);
    expect(events[0]?.id).toBe('new-p101');
  });
});

describe('format helpers', () => {
  it('shows the last two topic segments and a compact payload value', () => {
    expect(formatTopicShort('HalabjaWTP/P101/Current')).toBe('P101 / Current');
    expect(formatEventValue({ value: 12.456 })).toBe('12.46');
    expect(formatEventValue(true)).toBe('true');
    expect(formatEventValue('running')).toBe('running');
  });

  it('reports age from the newest process message', () => {
    const now = Date.parse('2026-09-06T20:18:00.000Z');
    const feed = [
      msg({ topic: 'a/Value', timestamp: new Date(now - 8_000).toISOString() }),
      msg({ topic: 'plant/edge/sim', timestamp: new Date(now).toISOString() }),
    ];
    expect(lastMessageAgeMs(feed, now)).toBe(8_000);
  });
});

describe('activity window constants', () => {
  it('covers one minute in twelve buckets so the chart matches the live buffer', () => {
    expect(ACTIVITY_BUCKETS * ACTIVITY_BUCKET_MS).toBe(60_000);
  });
});

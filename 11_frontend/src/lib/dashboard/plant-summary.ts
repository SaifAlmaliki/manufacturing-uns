import type { MqttMessage } from '../../types/uns';
import type { GraphqlSubscribedSignal } from '../../services/graphql/types';
import { formatAge, formatEventValue, selectRecentEvents } from './activity';

export type ConnectivitySummary = {
  serverCount: number;
  signalCount: number;
};

export type SignalSnapshotItem = {
  topic: string;
  label: string;
  asset?: string | null;
  unit?: string | null;
  value: string;
  age: string | null;
};

export function buildSignalSnapshot(
  signals: GraphqlSubscribedSignal[],
  feed: MqttMessage[],
  limit = 3,
): SignalSnapshotItem[] {
  const liveByTopic = new Map(selectRecentEvents(feed, 50).map((msg) => [msg.topic, msg]));
  const liveSignals = signals.filter((sig) => liveByTopic.has(sig.mqttTopic));
  const ordered = [
    ...liveSignals,
    ...signals.filter((sig) => !liveByTopic.has(sig.mqttTopic)),
  ].slice(0, limit);

  return ordered.map((sig) => {
    const live = liveByTopic.get(sig.mqttTopic);
    return {
      topic: sig.mqttTopic,
      label: sig.displayName,
      asset: sig.assetDisplayName,
      unit: sig.unitOfMeasure,
      value: live ? formatEventValue(live.payload) : '—',
      age: live ? formatAge(Date.now() - Date.parse(live.timestamp)) : null,
    };
  });
}

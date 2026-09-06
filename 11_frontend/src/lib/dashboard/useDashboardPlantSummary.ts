import { useEffect, useState } from 'react';
import { unsGraphQLClient } from '../../services/graphql/client';
import type { GraphqlSubscribedSignal } from '../../services/graphql/types';
import type { ConnectivitySummary } from './plant-summary';

export function useDashboardPlantSummary(enabled: boolean): {
  connectivity: ConnectivitySummary | null;
  signals: GraphqlSubscribedSignal[];
  loading: boolean;
} {
  const [connectivity, setConnectivity] = useState<ConnectivitySummary | null>(null);
  const [signals, setSignals] = useState<GraphqlSubscribedSignal[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!enabled) {
      setConnectivity(null);
      setSignals([]);
      return;
    }

    let cancelled = false;
    setLoading(true);

    void (async () => {
      try {
        const [servers, subscribed] = await Promise.all([
          unsGraphQLClient.getConnectivityServers('OPC_UA'),
          unsGraphQLClient.getSubscribedSignals(),
        ]);
        if (cancelled) return;
        setConnectivity({ serverCount: servers.length, signalCount: subscribed.length });
        setSignals(subscribed);
      } catch {
        if (!cancelled) {
          setConnectivity(null);
          setSignals([]);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [enabled]);

  return { connectivity, signals, loading };
}

import { AppSettings } from '../types/uns';
import { platformConfig } from '../lib/platform/config';

function httpToWs(httpUrl: string): string {
  if (httpUrl.startsWith('https://')) {
    return `wss://${httpUrl.slice('https://'.length)}`;
  }
  if (httpUrl.startsWith('http://')) {
    return `ws://${httpUrl.slice('http://'.length)}`;
  }
  if (httpUrl.startsWith('/')) {
    if (typeof window !== 'undefined') {
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
      return `${proto}://${window.location.host}${httpUrl}`;
    }
    return 'ws://localhost:8000/graphql';
  }
  return httpUrl;
}

function resolveGraphqlHttpUrl(): string {
  const envUrl = import.meta.env.VITE_GRAPHQL_URL?.trim();
  if (import.meta.env.PROD) {
    return envUrl || platformConfig.graphqlUrl;
  }
  return '/graphql';
}

const graphqlUrl = resolveGraphqlHttpUrl();

/**
 * Default settings reflecting conf/settings.yaml and environment config
 */
export const DEFAULT_APP_SETTINGS: AppSettings = {
  displayName: platformConfig.displayName,
  organization: platformConfig.organizationName,
  instance: platformConfig.instanceName,
  graphqlUrl,
  graphqlWsUrl: import.meta.env.VITE_GRAPHQL_WS_URL?.trim() || httpToWs(graphqlUrl),
  maxFeedBuffer: 500,
  staleThresholdMinutes: 5,
  autoScrollFeed: true,
  followSelectionInFeed: false,
};

export const STORAGE_KEYS = {
  SETTINGS: 'uns_console_settings_v1',
  BOOKMARKS: 'uns_console_bookmarks_v1',
  KAFKA_TOPICS: 'uns_console_kafka_topics_v1',
  HISTORIAN_PRESETS: 'uns_console_historian_presets_v1',
};

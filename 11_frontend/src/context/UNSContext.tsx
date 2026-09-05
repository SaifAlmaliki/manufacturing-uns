/**
 * Central UNS Application State Context
 */

import React, { createContext, useContext, useState, useEffect, useCallback, useRef, useMemo } from 'react';
import {
  UnsNode,
  MqttMessage,
  TopicBookmark,
  AppSettings,
  SystemHealthInfo,
} from '../types/uns';
import { unsGraphQLClient } from '../services/graphql/client';
import { DEFAULT_APP_SETTINGS, STORAGE_KEYS } from '../config/branding';
import { getNodeRole, hasNoTelemetryClock, isStaleCandidate, isNodeStale, isSyntheticUnsNode } from '../lib/uns/node-meta';
import { isSparkplugTopic } from '../lib/uns/sparkplug';
import { useAuth } from './AuthContext';

function httpToWs(httpUrl: string): string {
  if (httpUrl.startsWith('https://')) return `wss://${httpUrl.slice('https://'.length)}`;
  if (httpUrl.startsWith('http://')) return `ws://${httpUrl.slice('http://'.length)}`;
  if (httpUrl.startsWith('/') && typeof window !== 'undefined') {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    return `${proto}://${window.location.host}${httpUrl}`;
  }
  return httpUrl;
}

function loadSettings(): AppSettings {
  try {
    const saved = localStorage.getItem(STORAGE_KEYS.SETTINGS);
    if (saved) {
      const parsed = { ...DEFAULT_APP_SETTINGS, ...JSON.parse(saved) } as AppSettings;
      // Older builds stored port 8080 (MQTT) as GraphQL — breaks historian and tree queries.
      if (parsed.graphqlUrl?.includes(':8080')) {
        parsed.graphqlUrl = DEFAULT_APP_SETTINGS.graphqlUrl;
        parsed.graphqlWsUrl = httpToWs(parsed.graphqlUrl);
        localStorage.setItem(STORAGE_KEYS.SETTINGS, JSON.stringify(parsed));
      }
      return parsed;
    }
  } catch {
    // ignore
  }
  return DEFAULT_APP_SETTINGS;
}

export type NavigationTab = 'home' | 'explore' | 'sparkplug' | 'streams' | 'system' | 'users';

interface UNSContextType {
  activeTab: NavigationTab;
  setActiveTab: (tab: NavigationTab) => void;
  settings: AppSettings;
  updateSettings: (partial: Partial<AppSettings>) => void;
  health: SystemHealthInfo;
  rootNodes: UnsNode[];
  expandedNodes: Set<string>;
  toggleNodeExpanded: (topic: string) => Promise<void>;
  selectedNode: UnsNode | null;
  selectNode: (node: UnsNode | null) => void;
  treeLoading: boolean;
  refreshTree: () => Promise<void>;
  staleNodesCount: number;
  allLoadedNodes: UnsNode[];
  mqttFeed: MqttMessage[];
  isFeedPaused: boolean;
  setIsFeedPaused: (paused: boolean | ((prev: boolean) => boolean)) => void;
  feedTopicFilter: string;
  setFeedTopicFilter: (filter: string) => void;
  clearMqttFeed: () => void;
  followSelection: boolean;
  setFollowSelection: (follow: boolean) => void;
  bookmarks: TopicBookmark[];
  addBookmark: (topic: string, alias?: string, notes?: string) => void;
  removeBookmark: (topic: string) => void;
  isBookmarked: (topic: string) => boolean;
  jumpToTopicInTree: (topic: string) => Promise<void>;
  jumpToHistorian: (topic: string) => void;
  jumpToSparkplug: (metricName: string) => void;
  jumpToKafkaTopic: (topic: string) => void;
  historianInitialTopic: string;
  sparkplugInitialMetric: string;
  kafkaInitialTopic: string;
}

const UNSContext = createContext<UNSContextType | null>(null);

function attachChildren(nodes: UnsNode[], nodeChildrenMap: Map<string, UnsNode[]>): UnsNode[] {
  return nodes.map((node) => {
    const children = nodeChildrenMap.get(node.topic) ?? [];
    return {
      ...node,
      children: attachChildren(children, nodeChildrenMap),
      isLeaf: children.length === 0 ? node.isLeaf : false,
    };
  });
}

function patchNodeInMap(
  map: Map<string, UnsNode[]>,
  topic: string,
  patch: Partial<UnsNode>,
): Map<string, UnsNode[]> {
  let changed = false;
  const next = new Map<string, UnsNode[]>();
  for (const [parent, children] of map.entries()) {
    const updated = children.map((child) => {
      if (child.topic === topic) {
        changed = true;
        return { ...child, ...patch };
      }
      return child;
    });
    next.set(parent, updated);
  }
  return changed ? next : map;
}

export const UNSProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { isReady, isAuthenticated } = useAuth();
  const [activeTab, setActiveTab] = useState<NavigationTab>('home');
  const [settings, setSettings] = useState<AppSettings>(() => loadSettings());

  const [health, setHealth] = useState<SystemHealthInfo>(unsGraphQLClient.getHealth());
  const [rootNodes, setRootNodes] = useState<UnsNode[]>([]);
  const [nodeChildrenMap, setNodeChildrenMap] = useState<Map<string, UnsNode[]>>(new Map());
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());
  const [selectedNode, setSelectedNode] = useState<UnsNode | null>(null);
  const applyNodePatch = useCallback((topic: string, patch: Partial<UnsNode>) => {
    setSelectedNode((prev) => (prev?.topic === topic ? { ...prev, ...patch } : prev));
    setRootNodes((prev) => prev.map((n) => (n.topic === topic ? { ...n, ...patch } : n)));
    setNodeChildrenMap((prev) => patchNodeInMap(prev, topic, patch));
  }, []);

  const selectNode = useCallback((node: UnsNode | null) => {
    setSelectedNode(node);
    if (!node) return;

    if (isSyntheticUnsNode(node) && getNodeRole(node.nodeType) === 'sensor') {
      const end = new Date().toISOString();
      const start = new Date(Date.now() - 60 * 60 * 1000).toISOString();
      void unsGraphQLClient.getHistoricEvents(node.topic, start, end).then((events) => {
        if (events.length === 0) return;
        const latest = events.reduce((newest, event) =>
          new Date(event.timestamp).getTime() >= new Date(newest.timestamp).getTime() ? event : newest,
        );
        applyNodePatch(node.topic, {
          payload: latest.payload,
          lastUpdated: latest.timestamp,
          publisher: latest.publisher,
        });
      });
      return;
    }

    if (isSyntheticUnsNode(node)) return;

    void Promise.all([
      unsGraphQLClient.getUnsNodes([node.topic]),
      unsGraphQLClient.getTopicEnrichment(node.topic),
    ]).then(([nodes, enrichment]) => {
      if (!nodes[0]) return;
      const hydrated = nodes[0];
      applyNodePatch(hydrated.topic, {
        ...hydrated,
        properties: { ...enrichment, ...(hydrated.properties ?? {}) },
      });
    });
  }, [applyNodePatch]);
  const [treeLoading, setTreeLoading] = useState<boolean>(false);

  const [mqttFeed, setMqttFeed] = useState<MqttMessage[]>([]);
  const [isFeedPaused, setIsFeedPaused] = useState<boolean>(false);
  const [feedTopicFilter, setFeedTopicFilter] = useState<string>('#');
  const [followSelection, setFollowSelection] = useState<boolean>(false);

  const [historianInitialTopic, setHistorianInitialTopic] = useState<string>('');
  const [sparkplugInitialMetric, setSparkplugInitialMetric] = useState<string>('');
  const [kafkaInitialTopic, setKafkaInitialTopic] = useState<string>('');

  const [bookmarks, setBookmarks] = useState<TopicBookmark[]>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEYS.BOOKMARKS);
      if (saved) return JSON.parse(saved);
    } catch {
      // ignore
    }
    return [];
  });

  useEffect(() => {
    unsGraphQLClient.setUrls(settings.graphqlUrl, settings.graphqlWsUrl);
  }, [settings.graphqlUrl, settings.graphqlWsUrl]);

  useEffect(() => {
    if (!isReady || !isAuthenticated) return;
    let cancelled = false;
    void unsGraphQLClient.getHierarchy().then((next) => {
      if (cancelled || !next) return;
      setSettings((prev) =>
        prev.organization === next.enterprise ? prev : { ...prev, organization: next.enterprise },
      );
    });
    return () => {
      cancelled = true;
    };
  }, [isReady, isAuthenticated]);

  useEffect(() => {
    return unsGraphQLClient.onHealthChange((h) => setHealth(h));
  }, []);

  const updateSettings = useCallback((partial: Partial<AppSettings>) => {
    setSettings((prev) => {
      const updated = { ...prev, ...partial };
      try {
        localStorage.setItem(STORAGE_KEYS.SETTINGS, JSON.stringify(updated));
      } catch {
        // ignore
      }
      if (partial.graphqlUrl || partial.graphqlWsUrl) {
        unsGraphQLClient.setUrls(updated.graphqlUrl, updated.graphqlWsUrl);
      }
      return updated;
    });
  }, []);

  const saveBookmarks = (list: TopicBookmark[]) => {
    setBookmarks(list);
    try {
      localStorage.setItem(STORAGE_KEYS.BOOKMARKS, JSON.stringify(list));
    } catch {
      // ignore
    }
  };

  const addBookmark = (topic: string, alias?: string, notes?: string) => {
    if (bookmarks.some((b) => b.topic === topic)) return;
    saveBookmarks([
      ...bookmarks,
      {
        topic,
        alias: alias || topic.split('/').pop() || topic,
        addedAt: new Date().toISOString(),
        notes,
      },
    ]);
  };

  const removeBookmark = (topic: string) => {
    saveBookmarks(bookmarks.filter((b) => b.topic !== topic));
  };

  const isBookmarked = (topic: string) => bookmarks.some((b) => b.topic === topic);

  const fetchRoots = useCallback(async () => {
    setTreeLoading(true);
    try {
      const roots = await unsGraphQLClient.getUnsRootNodes();
      setRootNodes(roots);
      setNodeChildrenMap(new Map());
      setExpandedNodes(new Set());
      setSelectedNode((prev) => prev ?? (roots.length > 0 ? roots[0] : null));
    } finally {
      setTreeLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isReady && isAuthenticated) {
      void fetchRoots();
    }
  }, [isReady, isAuthenticated, fetchRoots]);

  const toggleNodeExpanded = async (topic: string) => {
    if (expandedNodes.has(topic)) {
      setExpandedNodes((prev) => {
        const next = new Set(prev);
        next.delete(topic);
        return next;
      });
      return;
    }

    try {
      const children = await unsGraphQLClient.getUnsNodeChildren(topic);
      setNodeChildrenMap((prev) => new Map(prev).set(topic, children));
      setExpandedNodes((prev) => new Set(prev).add(topic));
    } catch (e) {
      console.error('Failed to expand node children', e);
    }
  };

  const treeWithChildren = useMemo(
    () => attachChildren(rootNodes, nodeChildrenMap),
    [rootNodes, nodeChildrenMap],
  );

  const allLoadedNodes = useMemo(() => {
    const list: UnsNode[] = [];
    const visited = new Set<string>();
    const traverse = (nodes: UnsNode[]) => {
      for (const node of nodes) {
        if (visited.has(node.topic)) continue;
        visited.add(node.topic);
        list.push(node);
        if (node.children?.length) traverse(node.children);
      }
    };
    traverse(treeWithChildren);
    return list;
  }, [treeWithChildren]);

  const staleNodesCount = allLoadedNodes.filter((n) => {
    if (!isStaleCandidate(n)) return false
    return isNodeStale(n.lastUpdated, settings.staleThresholdMinutes || 5)
  }).length;

  const jumpToTopicInTree = async (targetTopic: string) => {
    setActiveTab('home');
    if (window.location.hash !== '#/tree' && window.location.hash !== '#/') {
      window.location.hash = '#/tree';
    }

    const segments = targetTopic.split('/').filter(Boolean);
    const expanded = new Set(expandedNodes);
    let currentPath = '';

    for (let i = 0; i < segments.length - 1; i++) {
      currentPath = currentPath ? `${currentPath}/${segments[i]}` : segments[i];
      expanded.add(currentPath);
      const children = await unsGraphQLClient.getUnsNodeChildren(currentPath);
      setNodeChildrenMap((prev) => new Map(prev).set(currentPath, children));
    }

    setExpandedNodes(expanded);

    const nodes = await unsGraphQLClient.getUnsNodes([targetTopic]);
    if (nodes.length > 0) {
      setSelectedNode(nodes[0]);
    }
  };

  const jumpToHistorian = (topic: string) => {
    setHistorianInitialTopic(topic);
    setActiveTab('explore');
    window.location.hash = '#/historian';
  };

  const jumpToSparkplug = (metricName: string) => {
    setSparkplugInitialMetric(metricName);
    setActiveTab('sparkplug');
    window.location.hash = '#/sparkplug';
  };

  const jumpToKafkaTopic = (topic: string) => {
    setKafkaInitialTopic(topic);
    setActiveTab('streams');
    window.location.hash = '#/streams';
  };

  const isPausedRef = useRef(isFeedPaused);
  isPausedRef.current = isFeedPaused;

  const maxBufferRef = useRef(settings.maxFeedBuffer);
  maxBufferRef.current = settings.maxFeedBuffer;

  const selectedNodeRef = useRef(selectedNode);
  selectedNodeRef.current = selectedNode;

  useEffect(() => {
    let effectiveTopics: string[] = ['#'];

    if (followSelection && selectedNodeRef.current) {
      effectiveTopics = [`${selectedNodeRef.current.topic}/#`, selectedNodeRef.current.topic];
    } else if (feedTopicFilter.trim()) {
      effectiveTopics = feedTopicFilter
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean);
      if (effectiveTopics.length === 0) effectiveTopics = ['#'];
    }

    const unsubscribe = unsGraphQLClient.subscribeMqttMessages(effectiveTopics, (msg) => {
      if (isPausedRef.current || isSparkplugTopic(msg.topic)) {
        return;
      }

      setMqttFeed((prev) => {
        const next = [msg, ...prev];
        const cap = maxBufferRef.current || 500;
        return next.length > cap ? next.slice(0, cap) : next;
      });

      const patch = { payload: msg.payload, lastUpdated: msg.timestamp };

      setRootNodes((prev) =>
        prev.map((node) => (node.topic === msg.topic ? { ...node, ...patch } : node)),
      );

      setNodeChildrenMap((prev) => patchNodeInMap(prev, msg.topic, patch));

      if (selectedNodeRef.current?.topic === msg.topic) {
        setSelectedNode((prev) => (prev ? { ...prev, ...patch } : prev));
      }
    });

    return unsubscribe;
  }, [feedTopicFilter, followSelection, health.graphqlWs]);

  const clearMqttFeed = () => {
    setMqttFeed([]);
  };

  return (
    <UNSContext.Provider
      value={{
        activeTab,
        setActiveTab,
        settings,
        updateSettings,
        health,
        rootNodes: treeWithChildren,
        expandedNodes,
        toggleNodeExpanded,
        selectedNode,
        selectNode,
        treeLoading,
        refreshTree: fetchRoots,
        staleNodesCount,
        allLoadedNodes,
        mqttFeed,
        isFeedPaused,
        setIsFeedPaused,
        feedTopicFilter,
        setFeedTopicFilter,
        clearMqttFeed,
        followSelection,
        setFollowSelection,
        bookmarks,
        addBookmark,
        removeBookmark,
        isBookmarked,
        jumpToTopicInTree,
        jumpToHistorian,
        jumpToSparkplug,
        jumpToKafkaTopic,
        historianInitialTopic,
        sparkplugInitialMetric,
        kafkaInitialTopic,
      }}
    >
      {children}
    </UNSContext.Provider>
  );
};

export const useUNS = () => {
  const ctx = useContext(UNSContext);
  if (!ctx) {
    throw new Error('useUNS must be used within a UNSProvider');
  }
  return ctx;
};

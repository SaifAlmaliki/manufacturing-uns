import React, { useState } from 'react';
import {
  Folder,
  FolderOpen,
  FileCode,
  Search,
  RefreshCw,
  Bookmark,
  BookmarkPlus,
  AlertCircle,
  Layers,
} from 'lucide-react';
import { UnsNode } from '../../types/uns';
import { useUNS } from '../../context/UNSContext';
import {
  getNodeRole,
  hasLiveTelemetry,
  isNodeStale,
  isStaleCandidate,
} from '../../lib/uns/node-meta';
import { tagMatchesNode } from '../../lib/condition-monitoring/match-tags';
import type { GraphqlConnectivityTag } from '../../services/graphql/types';
import { consoleTokens } from '../ui/console-ui';
import { ConsoleTreeNode } from '../ui/console-tree';

export const UnsTreeView: React.FC<{
  connectedTags?: GraphqlConnectivityTag[];
}> = ({ connectedTags = [] }) => {
  const {
    rootNodes,
    expandedNodes,
    toggleNodeExpanded,
    selectedNode,
    selectNode,
    treeLoading,
    refreshTree,
    settings,
    isBookmarked,
    addBookmark,
    removeBookmark,
  } = useUNS();

  const [searchQuery, setSearchQuery] = useState('');

  const isStale = (node: UnsNode) => {
    if (!isStaleCandidate(node)) return false;
    return isNodeStale(node.lastUpdated, settings.staleThresholdMinutes || 5);
  };

  const renderNode = (node: UnsNode, level = 0) => {
    const isExpanded = expandedNodes.has(node.topic);
    const isSelected = selectedNode?.topic === node.topic;
    const stale = isStale(node);
    const live = hasLiveTelemetry(node.payload);
    const connected = connectedTags.some((tag) => tagMatchesNode(tag, node));
    const bookmarked = isBookmarked(node.topic);
    const isExpandable =
      !['DEVICE_depth_3', 'NESTED_ATTRIBUTE'].includes(node.nodeType) ||
      (node.children?.length ?? 0) > 0;

    if (searchQuery.trim() !== '' && !node.topic.toLowerCase().includes(searchQuery.toLowerCase())) {
      const hasMatchingChild = node.children?.some((c) =>
        c.topic.toLowerCase().includes(searchQuery.toLowerCase())
      );
      if (!hasMatchingChild) return null;
    }

    const statusDot = stale
      ? 'bg-amber-500'
      : live
        ? 'bg-emerald-500'
        : 'bg-zinc-600';

    return (
      <div key={node.topic} id={`uns-node-${node.topic.replace(/[^a-zA-Z0-9]/g, '-')}`}>
        <ConsoleTreeNode
          level={level}
          name={node.name}
          expandable={isExpandable}
          expanded={isExpanded}
          selected={isSelected}
          collapsePlaceholder={<span className={`size-1.5 shrink-0 rounded-full ${statusDot}`} />}
          onToggle={() => {
            void toggleNodeExpanded(node.topic);
          }}
          onRowClick={() => {
            selectNode(node);
            if (isExpandable && !expandedNodes.has(node.topic)) {
              void toggleNodeExpanded(node.topic);
            }
          }}
          branch={
            isExpandable && isExpanded && node.children && node.children.length > 0
              ? node.children.map((child) => renderNode(child, level + 1))
              : undefined
          }
        >
          <div className="flex min-w-0 flex-1 items-center gap-2">
            {!isExpandable ? (
              <FileCode className="size-3.5 shrink-0 text-emerald-500" />
            ) : isExpanded ? (
              <FolderOpen className="size-3.5 shrink-0 text-[#FF7A00]" />
            ) : (
              <Folder className="size-3.5 shrink-0 text-muted-foreground" />
            )}

            <span className="truncate" title={node.name}>
              {node.name}
            </span>
            {connected && (
              <span
                aria-label="Signals connected"
                title="Signals connected"
                className={`ml-auto size-2 shrink-0 rounded-full ${
                  isSelected ? 'bg-emerald-400' : 'bg-emerald-500'
                }`}
              />
            )}
          </div>

          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              if (bookmarked) removeBookmark(node.topic);
              else addBookmark(node.topic);
            }}
            className="shrink-0 rounded p-0.5 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 hover:text-[#FF7A00]"
            title={bookmarked ? 'Remove bookmark' : 'Bookmark'}
          >
            {bookmarked ? (
              <Bookmark className="size-3.5 fill-[#FF7A00] text-[#FF7A00]" />
            ) : (
              <BookmarkPlus className="size-3.5" />
            )}
          </button>
        </ConsoleTreeNode>
      </div>
    );
  };

  return (
    <div id="uns-tree-panel" className={consoleTokens.pane}>
      <div className={`${consoleTokens.paneHeader} space-y-3`}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Layers className="size-4 text-[#FF7A00]" />
            <span className="text-sm font-semibold text-foreground">Plant tree</span>
          </div>
          <button
            onClick={() => refreshTree()}
            disabled={treeLoading}
            className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-[#FF7A00]"
            title="Refresh tree"
          >
            <RefreshCw className={`size-4 ${treeLoading ? 'animate-spin' : ''}`} />
          </button>
        </div>

        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <input
            type="text"
            placeholder="Filter topics..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className={`${consoleTokens.input} pl-9`}
          />
        </div>
      </div>

      <div className="min-w-0 flex-1 overflow-x-auto overflow-y-auto p-2">
        {rootNodes.length === 0 ? (
          <div className="flex flex-col items-center justify-center px-4 py-12 text-center">
            <AlertCircle className="mb-2 size-8 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">No namespace nodes found</p>
            <p className="mt-1 text-xs text-muted-foreground">Connecting to GraphQL backend…</p>
          </div>
        ) : (
          rootNodes.map((node) => renderNode(node))
        )}
      </div>

      <div className="flex shrink-0 items-center justify-between border-t border-border px-3 py-2 text-xs text-muted-foreground">
        <span>Stale: {settings.staleThresholdMinutes}m</span>
        <span className="tabular-nums">Roots: {rootNodes.length}</span>
      </div>
    </div>
  );
};

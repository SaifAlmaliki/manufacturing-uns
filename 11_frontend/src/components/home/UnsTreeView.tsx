import React, { useState } from 'react';
import {
  Folder,
  FolderOpen,
  FileCode,
  ChevronRight,
  ChevronDown,
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
import { consoleTokens } from '../ui/console-ui';

export const UnsTreeView: React.FC = () => {
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
      <div key={node.topic} className="select-none">
        <div
          id={`uns-node-${node.topic.replace(/[^a-zA-Z0-9]/g, '-')}`}
          onClick={() => {
            selectNode(node);
            if (isExpandable && !expandedNodes.has(node.topic)) {
              void toggleNodeExpanded(node.topic);
            }
          }}
          style={{ paddingLeft: `${level * 14 + 8}px` }}
          className={`group flex cursor-pointer items-center justify-between rounded-lg px-2 py-1.5 text-sm transition-colors ${
            isSelected
              ? 'bg-[#FF7A00]/15 text-[#FF7A00]'
              : 'text-zinc-300 hover:bg-zinc-800/60 hover:text-white'
          }`}
        >
          <div className="flex min-w-0 flex-1 items-center gap-2">
            {isExpandable ? (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  toggleNodeExpanded(node.topic);
                }}
                className="rounded p-0.5 text-zinc-500 hover:text-[#FF7A00]"
              >
                {isExpanded ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
              </button>
            ) : (
              <span className={`size-1.5 shrink-0 rounded-full ${statusDot}`} />
            )}

            {!isExpandable ? (
              <FileCode className="size-3.5 shrink-0 text-emerald-500" />
            ) : isExpanded ? (
              <FolderOpen className="size-3.5 shrink-0 text-[#FF7A00]" />
            ) : (
              <Folder className="size-3.5 shrink-0 text-zinc-500" />
            )}

            <span className="truncate">{node.name}</span>
          </div>

          <button
            onClick={(e) => {
              e.stopPropagation();
              if (bookmarked) removeBookmark(node.topic);
              else addBookmark(node.topic);
            }}
            className="shrink-0 rounded p-0.5 text-zinc-600 opacity-0 transition-opacity group-hover:opacity-100 hover:text-[#FF7A00]"
            title={bookmarked ? 'Remove bookmark' : 'Bookmark'}
          >
            {bookmarked ? (
              <Bookmark className="size-3.5 fill-[#FF7A00] text-[#FF7A00]" />
            ) : (
              <BookmarkPlus className="size-3.5" />
            )}
          </button>
        </div>

        {isExpanded && node.children && node.children.length > 0 && (
          <div className="ml-3 border-l border-zinc-800">
            {node.children.map((child) => renderNode(child, level + 1))}
          </div>
        )}
      </div>
    );
  };

  return (
    <div id="uns-tree-panel" className={consoleTokens.pane}>
      <div className={`${consoleTokens.paneHeader} space-y-3`}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Layers className="size-4 text-[#FF7A00]" />
            <span className="text-sm font-semibold text-white">Namespace Tree</span>
          </div>
          <button
            onClick={() => refreshTree()}
            disabled={treeLoading}
            className="rounded-lg p-1.5 text-zinc-500 transition-colors hover:bg-zinc-800 hover:text-[#FF7A00]"
            title="Refresh tree"
          >
            <RefreshCw className={`size-4 ${treeLoading ? 'animate-spin' : ''}`} />
          </button>
        </div>

        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-zinc-500" />
          <input
            type="text"
            placeholder="Filter topics..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className={`${consoleTokens.input} pl-9`}
          />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-2">
        {rootNodes.length === 0 ? (
          <div className="flex flex-col items-center justify-center px-4 py-12 text-center">
            <AlertCircle className="mb-2 size-8 text-zinc-600" />
            <p className="text-sm text-zinc-400">No namespace nodes found</p>
            <p className="mt-1 text-xs text-zinc-600">Connecting to GraphQL backend…</p>
          </div>
        ) : (
          rootNodes.map((node) => renderNode(node))
        )}
      </div>

      <div className="flex shrink-0 items-center justify-between border-t border-zinc-800 px-3 py-2 text-xs text-zinc-500">
        <span>Stale: {settings.staleThresholdMinutes}m</span>
        <span className="tabular-nums">Roots: {rootNodes.length}</span>
      </div>
    </div>
  );
};

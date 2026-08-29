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
  Hash,
} from 'lucide-react';
import { UnsNode } from '../../types/uns';
import { useUNS } from '../../context/UNSContext';
import {
  getNodeRole,
  getNodeRoleLabel,
  hasLiveTelemetry,
  isNodeStale,
  isStaleCandidate,
} from '../../lib/uns/node-meta';

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

  // Render a single node row and its children recursively
  const renderNode = (node: UnsNode, level = 0) => {
    const isExpanded = expandedNodes.has(node.topic);
    const isSelected = selectedNode?.topic === node.topic;
    const stale = isStale(node);
    const role = getNodeRole(node.nodeType);
    const live = hasLiveTelemetry(node.payload);
    const bookmarked = isBookmarked(node.topic);
    const isExpandable =
      !['DEVICE_depth_3', 'NESTED_ATTRIBUTE'].includes(node.nodeType) ||
      (node.children?.length ?? 0) > 0;

    // Filter by search query if present
    if (searchQuery.trim() !== '' && !node.topic.toLowerCase().includes(searchQuery.toLowerCase())) {
      const hasMatchingChild = node.children?.some((c) =>
        c.topic.toLowerCase().includes(searchQuery.toLowerCase())
      );
      if (!hasMatchingChild) return null;
    }

    return (
      <div key={node.topic} className="select-none">
        <div
          id={`uns-node-${node.topic.replace(/[^a-zA-Z0-9]/g, '-')}`}
          onClick={() => selectNode(node)}
          style={{ paddingLeft: `${level * 12 + 4}px` }}
          className={`flex items-center justify-between py-0.5 px-1.5 rounded text-[11px] font-mono cursor-pointer transition-colors group ${
            isSelected
              ? 'bg-amber-50 dark:bg-[#1E293B] text-amber-900 dark:text-[#FFC107] font-semibold border border-amber-300 dark:border-[#334155]'
              : 'text-[#0F172A] dark:text-[#E2E8F0] hover:bg-slate-100 dark:hover:bg-[#1E293B]/50 hover:text-black dark:hover:text-[#F8FAFC] border border-transparent'
          } ${stale ? 'opacity-90' : ''}`}
        >
          {/* Node Icon & Expansion Caret */}
          <div className="flex items-center gap-1.5 min-w-0 flex-1">
            {isExpandable ? (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  toggleNodeExpanded(node.topic);
                }}
                className="p-0.5 hover:bg-slate-200 dark:hover:bg-[#334155] rounded text-[#334155] hover:text-[#0F172A] dark:hover:text-[#F8FAFC]"
              >
                {isExpanded ? (
                  <ChevronDown className="w-3 h-3 text-amber-600 dark:text-[#FFC107]" />
                ) : (
                  <ChevronRight className="w-3 h-3 text-[#334155] dark:text-[#94A3B8]" />
                )}
              </button>
            ) : (
              <span className="w-3 h-3 flex items-center justify-center">
                <span className={`w-1.5 h-1.5 rounded-full ${isSelected ? 'bg-amber-500 dark:bg-[#FFC107]' : 'bg-emerald-500 dark:bg-[#10B981]'}`} />
              </span>
            )}

            {/* Folder / Metric Icon */}
            {!isExpandable ? (
              <FileCode className="w-3 h-3 text-emerald-600 dark:text-[#10B981] shrink-0" />
            ) : (
              isExpanded ? (
                <FolderOpen className="w-3 h-3 text-amber-600 dark:text-[#FFC107] shrink-0" />
              ) : (
                <Folder className="w-3 h-3 text-slate-700 dark:text-[#64748B] shrink-0" />
              )
            )}

            {/* Node Name */}
            <span className="truncate font-mono text-[11px] font-medium text-[#0F172A] dark:text-[#F1F5F9]">{node.name}</span>

            {/* Role / status tags */}
            <span className="px-1 py-0 rounded bg-slate-100 dark:bg-[#0B0B0C] border border-[#CBD5E1] dark:border-[#334155] text-[#64748B] dark:text-[#94A3B8] text-[8px] font-mono shrink-0">
              {getNodeRoleLabel(role)}
            </span>
            {live && (
              <span className="px-1 py-0 rounded bg-emerald-100 dark:bg-emerald-950/60 border border-emerald-300 dark:border-emerald-800/60 text-emerald-800 dark:text-[#10B981] text-[8px] font-mono shrink-0">
                LIVE
              </span>
            )}
            {stale && (
              <span className="px-1 py-0 rounded bg-amber-100 dark:bg-amber-950/80 border border-amber-300 dark:border-amber-800/60 text-amber-800 dark:text-[#FFC107] text-[8px] font-mono shrink-0">
                STALE
              </span>
            )}
          </div>

          {/* Right Action Icons on Hover */}
          <div className="flex items-center space-x-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
            <button
              onClick={(e) => {
                e.stopPropagation();
                if (bookmarked) {
                  removeBookmark(node.topic);
                } else {
                  addBookmark(node.topic);
                }
              }}
              className="p-0.5 hover:bg-slate-200 dark:hover:bg-[#334155] rounded text-[#64748B] hover:text-amber-600 dark:hover:text-[#FFC107]"
              title={bookmarked ? 'Remove Bookmark' : 'Bookmark Topic'}
            >
              {bookmarked ? (
                <Bookmark className="w-3 h-3 text-amber-600 dark:text-[#FFC107] fill-current" />
              ) : (
                <BookmarkPlus className="w-3 h-3" />
              )}
            </button>
          </div>
        </div>

        {/* Render child nodes if expanded */}
        {isExpanded && node.children && node.children.length > 0 && (
          <div className="border-l border-[#CBD5E1] dark:border-[#1E293B] ml-2">
            {node.children.map((child) => renderNode(child, level + 1))}
          </div>
        )}
      </div>
    );
  };

  return (
    <div id="uns-tree-panel" className="flex flex-col h-full bg-[#FFFFFF] dark:bg-[#0B0B0C] border-r border-[#E2E8F0] dark:border-[#1E293B]">
      {/* Header & Search */}
      <div className="p-2.5 border-b border-[#E2E8F0] dark:border-[#1E293B] bg-[#F8FAFC] dark:bg-[#111114] space-y-2 shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <Hash className="w-3.5 h-3.5 text-amber-600 dark:text-[#FFC107]" />
            <span className="font-serif font-bold text-[#0F172A] dark:text-[#F8FAFC] text-xs tracking-wide uppercase">
              ISA-95 Hierarchy
            </span>
          </div>
          <button
            onClick={() => refreshTree()}
            disabled={treeLoading}
            className="p-1 rounded hover:bg-slate-200 dark:hover:bg-[#1E293B] text-[#64748B] dark:text-[#94A3B8] hover:text-amber-600 dark:hover:text-[#FFC107] transition-colors cursor-pointer"
            title="Refresh Hierarchy Roots"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${treeLoading ? 'animate-spin' : ''}`} />
          </button>
        </div>

        {/* Tree Search Box */}
        <div className="relative">
          <Search className="w-3 h-3 text-[#64748B] absolute left-2 top-2 pointer-events-none" />
          <input
            type="text"
            placeholder="Filter namespace topics..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full bg-white dark:bg-[#0B0B0C] border border-[#CBD5E1] dark:border-[#1E293B] rounded pl-7 pr-2 py-1 text-[11px] text-[#0F172A] dark:text-[#F8FAFC] placeholder-[#64748B] focus:outline-none focus:border-amber-500 dark:focus:border-[#FFC107] font-mono"
          />
        </div>
      </div>

      {/* Query Banner */}
      <div className="px-2.5 py-1 bg-slate-100 dark:bg-[#111114]/70 border-b border-[#E2E8F0] dark:border-[#1E293B] flex items-center justify-between text-[9px] text-[#64748B] font-mono">
        <span>Query: getUnsNodes(["+"])</span>
        <span className="text-amber-700 dark:text-[#FFC107] font-medium">Single-level (+)</span>
      </div>

      {/* Tree Body */}
      <div className="flex-1 overflow-y-auto p-1.5 space-y-0.5 scrollbar-thin scrollbar-thumb-slate-300 dark:scrollbar-thumb-[#1E293B]">
        {rootNodes.length === 0 && !treeLoading && (
          <div className="text-center py-8 text-[#64748B] text-xs font-mono">
            <AlertCircle className="w-5 h-5 mx-auto mb-2 text-[#475569]" />
            <p>No root namespace nodes found.</p>
            <p className="text-[9px] mt-1 text-[#64748B]">Connecting to 07_uns_graphql...</p>
          </div>
        )}

        {rootNodes.map((node) => renderNode(node, 0))}
      </div>

      {/* Footer Info */}
      <div className="p-2 border-t border-[#E2E8F0] dark:border-[#1E293B] bg-[#F8FAFC] dark:bg-[#111114] text-[9px] text-[#64748B] font-mono flex items-center justify-between">
        <span>Stale: {settings.staleThresholdMinutes}m</span>
        <span>Roots: {rootNodes.length}</span>
      </div>
    </div>
  );
};

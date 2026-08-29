import React from 'react';
import { AlertTriangle, X, ExternalLink, Clock } from 'lucide-react';
import { useUNS } from '../../context/UNSContext';
import {
  formatAge,
  getNodeRoleLabel,
  getNodeRole,
  isNodeStale,
  isStaleCandidate,
} from '../../lib/uns/node-meta';

interface StaleNodesDrawerProps {
  isOpen: boolean;
  onClose: () => void;
}

export const StaleNodesDrawer: React.FC<StaleNodesDrawerProps> = ({ isOpen, onClose }) => {
  const { allLoadedNodes, settings, jumpToTopicInTree } = useUNS();

  if (!isOpen) return null;

  const thresholdMinutes = settings.staleThresholdMinutes || 5;

  const staleNodes = allLoadedNodes.filter(
    (n) => isStaleCandidate(n) && isNodeStale(n.lastUpdated, thresholdMinutes),
  );

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-black/70 backdrop-blur-xs flex justify-end">
      <div className="w-full max-w-md bg-[#111114] border-l border-[#1E293B] h-full flex flex-col shadow-2xl animate-in slide-in-from-right duration-200">
        <div className="p-3.5 bg-[#111114] border-b border-[#1E293B] flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-[#FFC107]" />
            <span className="font-bold text-[#F8FAFC] text-xs uppercase tracking-wider">Stale Telemetry Nodes</span>
            <span className="px-2 py-0.5 rounded bg-[#0B0B0C] border border-amber-500/40 text-[#FFC107] text-[10px] font-mono font-bold">
              {staleNodes.length}
            </span>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded bg-[#0B0B0C] border border-[#1E293B] hover:bg-[#1E293B] text-[#64748B] hover:text-[#F8FAFC] cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-3 bg-amber-950/20 border-b border-amber-900/30 text-[10px] font-mono text-amber-300/90">
          Only <b>sensor leaves</b> with telemetry are tracked. Structural nodes (Enterprise → Cell) and
          equipment folders (G1) are containers — expand them in the tree to reach ProcessValue → Temperature.
        </div>

        <div className="flex-1 overflow-y-auto p-3 space-y-2 font-mono text-xs bg-[#050505] scrollbar-thin scrollbar-thumb-[#1E293B]">
          {staleNodes.length === 0 ? (
            <div className="text-center py-12 text-[#64748B]">
              <Clock className="w-8 h-8 mx-auto mb-2 text-[#1E293B]" />
              <p className="text-[#94A3B8]">No stale sensor nodes detected.</p>
              <p className="text-[10px] mt-1 text-[#64748B]">
                Expand to <b>G1 → ProcessValue → Temperature</b> to inspect live values.
              </p>
            </div>
          ) : (
            staleNodes.map((node) => (
              <div
                key={node.topic}
                className="p-3 rounded bg-[#111114] border border-[#1E293B] hover:border-[#334155] space-y-1.5 transition-colors"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold text-[#F8FAFC] truncate max-w-xs text-xs">{node.name}</span>
                  <div className="flex items-center gap-1 shrink-0">
                    <span className="px-1 py-0 rounded bg-[#0B0B0C] border border-[#334155] text-[#94A3B8] text-[9px]">
                      {getNodeRoleLabel(getNodeRole(node.nodeType))}
                    </span>
                    <span className="px-1.5 py-0.2 rounded bg-amber-950/60 border border-amber-800/40 text-amber-400 text-[10px]">
                      {formatAge(node.lastUpdated)}
                    </span>
                  </div>
                </div>

                <div className="text-[10px] text-[#94A3B8] break-all">{node.topic}</div>

                <div className="flex items-center justify-between pt-1 text-[9px] text-[#64748B]">
                  <span>Pub: {node.publisher || 'unknown'}</span>
                  <button
                    onClick={() => {
                      jumpToTopicInTree(node.topic);
                      onClose();
                    }}
                    className="flex items-center gap-1 text-[#FFC107] hover:text-[#FFB300] font-semibold cursor-pointer"
                  >
                    <ExternalLink className="w-3 h-3" />
                    <span>Open in UNS Tree</span>
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};

import React, { useState, useEffect } from 'react';
import {
  Radio,
  Search,
  ExternalLink,
  Shield,
  Binary,
  RefreshCw,
  Info,
} from 'lucide-react';
import { SparkplugNode, SparkplugMetric } from '../../types/uns';
import { unsGraphQLClient } from '../../services/graphql/client';
import { useUNS } from '../../context/UNSContext';

export const SparkplugView: React.FC = () => {
  const { jumpToTopicInTree, sparkplugInitialMetric } = useUNS();
  const [metricQuery, setMetricQuery] = useState(sparkplugInitialMetric || '');
  const [nodes, setNodes] = useState<SparkplugNode[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedBinaryMetric, setSelectedBinaryMetric] = useState<SparkplugMetric | null>(null);

  const fetchSpbData = async () => {
    setLoading(true);
    try {
      const metricNames = metricQuery.trim() ? [metricQuery.trim()] : [];
      const data = metricNames.length
        ? await unsGraphQLClient.getSpbNodesByMetric(metricNames)
        : [];
      setNodes(data);
    } catch (e) {
      console.error('Failed to load Sparkplug nodes', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSpbData();
  }, [sparkplugInitialMetric]);

  // Check if string looks like an ISA-95 namespace path
  const isIsa95Path = (name: string) => {
    return name.includes('/') && (name.startsWith('CovestroAG') || name.split('/').length >= 3);
  };

  // Render Metric Value with Binary Handling
  const renderMetricValue = (metric: SparkplugMetric) => {
    if (metric.isBinary || metric.datatype === 'Bytes' || metric.datatype === 'File') {
      const byteLen = metric.binaryByteSize || (typeof metric.value === 'string' ? metric.value.length / 2 : 32);
      return (
        <div className="flex items-center gap-2">
          <span className="px-2 py-0.5 rounded bg-purple-950/80 border border-purple-800/80 text-purple-300 font-mono text-[10px] flex items-center gap-1">
            <Binary className="w-3 h-3 text-purple-400" />
            <span>[Binary Data: {byteLen} bytes]</span>
          </span>
          <button
            onClick={() => setSelectedBinaryMetric(metric)}
            className="text-[10px] text-[#FFC107] hover:underline font-mono cursor-pointer"
          >
            Hex View
          </button>
        </div>
      );
    }

    if (typeof metric.value === 'boolean') {
      return (
        <span className={`font-bold ${metric.value ? 'text-[#10B981]' : 'text-[#64748B]'}`}>
          {metric.value ? 'TRUE' : 'FALSE'}
        </span>
      );
    }

    if (typeof metric.value === 'number') {
      return <span className="text-[#FFC107] font-bold">{metric.value}</span>;
    }

    return <span className="text-[#F8FAFC]">{String(metric.value ?? '')}</span>;
  };

  return (
    <div id="sparkplug-explorer-view" className="flex-1 overflow-y-auto p-4 space-y-4 bg-[#050505] text-[#F8FAFC] font-mono text-xs">
      {/* Top Banner & SCADA Host Clarification */}
      <div className="bg-[#111114] border border-[#1E293B] rounded-lg p-4 space-y-3 shadow-lg">
        <div className="flex flex-wrap items-center justify-between gap-2 pb-3 border-b border-[#1E293B]">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded bg-[#0B0B0C] border border-[#1E293B] flex items-center justify-center text-purple-400">
              <Radio className="w-4 h-4" />
            </div>
            <div>
              <h2 className="font-bold text-[#F8FAFC] text-xs uppercase tracking-wider">Sparkplug B Explorer</h2>
              <p className="text-[10px] text-[#64748B] font-mono">
                Decoded edge nodes &amp; metrics from 07_uns_graphql Sparkplug mapper
              </p>
            </div>
          </div>

          {/* Hard Rule Notice */}
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-purple-950/30 border border-purple-800/40 text-[10px] text-purple-300">
            <Shield className="w-3.5 h-3.5 text-purple-400 shrink-0" />
            <span>Mapper is Telemetry-Only • UI does NOT issue NCMD/DCMD</span>
          </div>
        </div>

        {/* Search & Filter Bar */}
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative flex-1 min-w-[240px]">
            <Search className="w-3.5 h-3.5 text-[#64748B] absolute left-2.5 top-2 pointer-events-none" />
            <input
              type="text"
              value={metricQuery}
              onChange={(e) => setMetricQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && fetchSpbData()}
              placeholder="Search by metric name, ISA-95 path, or alias..."
              className="w-full bg-[#0B0B0C] border border-[#1E293B] rounded pl-8 pr-3 py-1.5 text-[#F8FAFC] text-[11px] focus:outline-none focus:border-[#FFC107]"
            />
          </div>

          <button
            onClick={fetchSpbData}
            disabled={loading}
            className="px-3 py-1.5 bg-[#FFC107] hover:bg-[#FFB300] disabled:opacity-50 text-[#0B0B0C] font-bold rounded transition-colors flex items-center gap-1.5 cursor-pointer font-mono text-xs"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            <span>Search Metrics</span>
          </button>
        </div>
      </div>

      {/* Edge Nodes & Metrics List */}
      <div className="space-y-4">
        {loading ? (
          <div className="text-center py-16 bg-[#111114] border border-[#1E293B] rounded-lg">
            <div className="inline-block animate-spin rounded-full h-5 w-5 border-t-2 border-b-2 border-[#FFC107] mb-2"></div>
            <p className="text-[#64748B]">Loading Sparkplug B Edge Nodes...</p>
          </div>
        ) : nodes.length === 0 ? (
          <div className="text-center py-16 bg-[#111114] border border-[#1E293B] rounded-lg text-[#64748B]">
            <Info className="w-8 h-8 mx-auto mb-2 text-[#64748B]" />
            <p>No Sparkplug B nodes or metrics matched the query.</p>
          </div>
        ) : (
          nodes.map((node) => (
            <div
              key={`${node.groupId}-${node.edgeNodeId}-${node.deviceId || ''}`}
              className="bg-[#111114] border border-[#1E293B] rounded-lg overflow-hidden shadow-lg"
            >
              {/* Node Header */}
              <div className="p-3 bg-[#111114] border-b border-[#1E293B] flex flex-wrap items-center justify-between gap-2 text-xs">
                <div className="flex items-center gap-3">
                  <div className="flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-[#10B981] shadow-[0_0_6px_rgba(16,185,129,0.8)]" />
                    <span className="font-bold text-[#F8FAFC] text-xs">
                      {node.groupId} / {node.edgeNodeId} {node.deviceId ? `• ${node.deviceId}` : ''}
                    </span>
                  </div>
                  <span className="px-2 py-0.5 rounded bg-[#0B0B0C] border border-[#1E293B] text-[#94A3B8] text-[9px]">
                    Seq: #{node.sequenceNumber ?? 0}
                  </span>
                </div>

                <div className="flex items-center gap-2 text-[10px] text-[#94A3B8]">
                  <span className="text-[#64748B]">Topic:</span>
                  <span className="text-purple-300 font-semibold">{node.topic}</span>
                </div>
              </div>

              {/* Metrics Table */}
              <div className="overflow-x-auto">
                <table className="w-full text-left text-[11px] font-mono">
                  <thead className="bg-[#0B0B0C] text-[#94A3B8] text-[10px] border-b border-[#1E293B] uppercase tracking-wider">
                    <tr>
                      <th className="py-2 px-3">Metric Name</th>
                      <th className="py-2 px-3">Alias</th>
                      <th className="py-2 px-3">Datatype</th>
                      <th className="py-2 px-3">Value</th>
                      <th className="py-2 px-3">Timestamp</th>
                      <th className="py-2 px-3">Flags</th>
                      <th className="py-2 px-3 text-right">UNS Link</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#1E293B]">
                    {node.metrics.map((metric, mIdx) => {
                      const matchesIsa95 = isIsa95Path(metric.name);

                      return (
                        <tr key={mIdx} className="hover:bg-[#1E293B]/40 transition-colors">
                          {/* Name */}
                          <td className="py-2 px-3 font-semibold text-[#F8FAFC] max-w-sm break-all">
                            {metric.name}
                          </td>

                          {/* Alias */}
                          <td className="py-2 px-3 text-[#94A3B8]">
                            {metric.alias !== undefined ? (
                              <span className="px-1.5 py-0.2 rounded bg-[#0B0B0C] text-[9px] text-[#FFC107] border border-[#1E293B]">
                                {metric.alias}
                              </span>
                            ) : (
                              '—'
                            )}
                          </td>

                          {/* Datatype */}
                          <td className="py-2 px-3 text-[#94A3B8]">
                            <span className="px-1.5 py-0.5 rounded bg-[#0B0B0C] border border-[#1E293B] text-[9px] text-purple-300">
                              {metric.datatype}
                            </span>
                          </td>

                          {/* Value */}
                          <td className="py-2 px-3">{renderMetricValue(metric)}</td>

                          {/* Timestamp */}
                          <td className="py-2 px-3 text-[#94A3B8] whitespace-nowrap text-[10px]">
                            {new Date(metric.timestamp).toLocaleTimeString()}
                          </td>

                          {/* Flags */}
                          <td className="py-2 px-3">
                            <div className="flex items-center gap-1">
                              {metric.isHistorical && (
                                <span className="px-1 py-0.2 rounded bg-[#0B0B0C] text-[#38BDF8] text-[9px] border border-[#1E293B]">
                                  HIST
                                </span>
                              )}
                              {metric.isTransient && (
                                <span className="px-1 py-0.2 rounded bg-[#0B0B0C] text-[#FFC107] text-[9px] border border-[#1E293B]">
                                  TRANS
                                </span>
                              )}
                            </div>
                          </td>

                          {/* Action to Jump to UNS tree */}
                          <td className="py-2 px-3 text-right">
                            {matchesIsa95 ? (
                              <button
                                onClick={() => jumpToTopicInTree(metric.name)}
                                className="flex items-center gap-1 px-2 py-0.5 rounded bg-[#FFC107]/15 border border-[#FFC107]/40 hover:bg-[#FFC107]/25 text-[#FFC107] text-[10px] font-semibold ml-auto transition-colors cursor-pointer"
                                title="Expand and select in ISA-95 UNS Tree"
                              >
                                <ExternalLink className="w-3 h-3" />
                                <span>Open in UNS</span>
                              </button>
                            ) : (
                              <span className="text-[#64748B] text-[10px]">Leaf</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Binary Hex Modal */}
      {selectedBinaryMetric && (
        <div className="fixed inset-0 bg-black/75 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-[#111114] border border-[#1E293B] rounded-lg max-w-2xl w-full p-4 space-y-3 shadow-2xl">
            <div className="flex items-center justify-between pb-2 border-b border-[#1E293B]">
              <div className="flex items-center gap-2">
                <Binary className="w-4 h-4 text-purple-400" />
                <span className="font-bold text-[#F8FAFC]">Binary Payload Inspector</span>
              </div>
              <button
                onClick={() => setSelectedBinaryMetric(null)}
                className="text-[#94A3B8] hover:text-[#F8FAFC] px-2 py-1 bg-[#0B0B0C] border border-[#1E293B] rounded text-xs cursor-pointer"
              >
                Close
              </button>
            </div>

            <div className="text-[10px] text-[#94A3B8] space-y-1">
              <div><b className="text-[#F8FAFC]">Metric:</b> {selectedBinaryMetric.name}</div>
              <div><b className="text-[#F8FAFC]">Data Type:</b> {selectedBinaryMetric.datatype}</div>
            </div>

            <div className="p-3 bg-[#0B0B0C] border border-[#1E293B] rounded font-mono text-xs overflow-x-auto text-purple-300 max-h-60 break-all leading-relaxed">
              {String(selectedBinaryMetric.value)}
            </div>

            <div className="text-[10px] text-[#64748B]">
              Protobuf binary streams are normalized safely on server without client-side protobuf execution.
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

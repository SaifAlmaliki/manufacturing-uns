import React, { useState } from 'react';
import { Download, ChevronDown, ChevronRight, Search, FileSpreadsheet, ExternalLink, Lock } from 'lucide-react';
import { HistoricEvent } from '../../types/uns';
import { JsonViewer } from '../common/JsonViewer';
import { useUNS } from '../../context/UNSContext';
import { useAuth } from '../../context/AuthContext';

interface HistorianTableProps {
  events: HistoricEvent[];
  isLoading: boolean;
  topicTitle: string;
}

export const HistorianTable: React.FC<HistorianTableProps> = ({ events, isLoading }) => {
  const { jumpToTopicInTree } = useUNS();
  const { hasPermission } = useAuth();
  const [filterText, setFilterText] = useState('');
  const [expandedEventId, setExpandedEventId] = useState<string | null>(null);

  const canExport = hasPermission('export_csv');

  // Filter events
  const filteredEvents = events.filter((ev) => {
    if (!filterText) return true;
    const q = filterText.toLowerCase();
    return (
      ev.topic.toLowerCase().includes(q) ||
      (ev.publisher && ev.publisher.toLowerCase().includes(q)) ||
      JSON.stringify(ev.payload).toLowerCase().includes(q)
    );
  });

  // UI-only CSV Export implementation
  const handleExportCsv = () => {
    if (!canExport || events.length === 0) return;

    // Collect all field names across events
    const allKeys = new Set<string>(['timestamp', 'topic', 'publisher', 'id']);
    events.forEach((ev) => {
      if (typeof ev.payload === 'object' && ev.payload !== null) {
        Object.keys(ev.payload).forEach((k) => allKeys.add(k));
      }
    });

    const headers = Array.from(allKeys);
    const csvRows = [headers.join(',')];

    events.forEach((ev) => {
      const row = headers.map((header) => {
        let val: unknown = '';
        if (header === 'timestamp') val = ev.timestamp;
        else if (header === 'topic') val = ev.topic;
        else if (header === 'publisher') val = ev.publisher || '';
        else if (header === 'id') val = ev.id;
        else if (typeof ev.payload === 'object' && ev.payload !== null) {
          val = (ev.payload as Record<string, unknown>)[header] ?? '';
        }

        // Escape CSV values
        const strVal = typeof val === 'object' ? JSON.stringify(val) : String(val);
        return `"${strVal.replace(/"/g, '""')}"`;
      });
      csvRows.push(row.join(','));
    });

    const blob = new Blob([csvRows.join('\n')], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.setAttribute('href', url);
    link.setAttribute('download', `historian_export_${Date.now()}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div id="historian-table-container" className="bg-[#111114] border border-[#1E293B] rounded-lg overflow-hidden flex flex-col">
      {/* Table Header Controls */}
      <div className="p-3 bg-[#111114] border-b border-[#1E293B] flex flex-wrap items-center justify-between gap-2 text-xs">
        <div className="flex items-center gap-2">
          <FileSpreadsheet className="w-4 h-4 text-[#10B981]" />
          <span className="font-bold text-[#F8FAFC] font-mono uppercase tracking-wider text-[11px]">Historical Records</span>
          <span className="px-1.5 py-0.2 rounded bg-[#1E293B] text-[#94A3B8] font-mono text-[9px]">
            {filteredEvents.length} / {events.length} rows
          </span>
        </div>

        <div className="flex items-center gap-2">
          {/* Quick Search */}
          <div className="relative">
            <Search className="w-3 h-3 text-[#64748B] absolute left-2 top-2 pointer-events-none" />
            <input
              type="text"
              placeholder="Search table..."
              value={filterText}
              onChange={(e) => setFilterText(e.target.value)}
              className="bg-[#0B0B0C] border border-[#1E293B] rounded pl-7 pr-2 py-1 text-[11px] text-[#F8FAFC] placeholder-[#64748B] focus:outline-none focus:border-[#FFC107] font-mono w-40 sm:w-52"
            />
          </div>

          {/* Export CSV Button with RBAC Permission Check */}
          <button
            id="export-historian-csv-btn"
            onClick={handleExportCsv}
            disabled={!canExport || events.length === 0}
            className={`flex items-center gap-1 px-2.5 py-1 rounded text-[10px] font-mono font-medium transition-colors ${
              canExport
                ? 'bg-[#10B981]/15 border border-[#10B981]/40 hover:bg-[#10B981]/25 text-[#10B981] disabled:opacity-40 cursor-pointer'
                : 'bg-[#1E293B]/40 border border-[#1E293B] text-[#64748B] cursor-not-allowed opacity-60'
            }`}
            title={canExport ? 'Export loaded historical rows to CSV' : 'Export CSV permission restricted by Administrator'}
          >
            {canExport ? <Download className="w-3.5 h-3.5" /> : <Lock className="w-3.5 h-3.5 text-rose-400" />}
            <span>Export CSV</span>
          </button>
        </div>
      </div>

      {/* Table Content */}
      <div className="overflow-x-auto max-h-[420px] scrollbar-thin scrollbar-thumb-[#1E293B]">
        <table className="w-full text-left text-[11px] font-mono">
          <thead className="bg-[#0B0B0C] text-[#94A3B8] text-[10px] sticky top-0 border-b border-[#1E293B] z-10 uppercase tracking-wider">
            <tr>
              <th className="w-8 py-2 px-3"></th>
              <th className="py-2 px-3">Timestamp</th>
              <th className="py-2 px-3">Topic</th>
              <th className="py-2 px-3">Publisher</th>
              <th className="py-2 px-3">Payload Summary</th>
              <th className="py-2 px-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#1E293B]">
            {isLoading ? (
              <tr>
                <td colSpan={6} className="py-12 text-center text-[#64748B]">
                  <div className="inline-block animate-spin rounded-full h-5 w-5 border-t-2 border-b-2 border-[#FFC107] mb-2"></div>
                  <p>Querying Timescale historian records...</p>
                </td>
              </tr>
            ) : filteredEvents.length === 0 ? (
              <tr>
                <td colSpan={6} className="py-8 text-center text-[#64748B]">
                  No historical records match the selected query criteria.
                </td>
              </tr>
            ) : (
              filteredEvents.map((ev) => {
                const isExpanded = expandedEventId === ev.id;
                const timeStr = new Date(ev.timestamp).toLocaleString();

                return (
                  <React.Fragment key={ev.id}>
                    <tr
                      onClick={() => setExpandedEventId(isExpanded ? null : ev.id)}
                      className={`hover:bg-[#1E293B]/40 cursor-pointer transition-colors ${
                        isExpanded ? 'bg-[#1E293B]/60' : ''
                      }`}
                    >
                      <td className="py-2 px-3 text-[#64748B]">
                        {isExpanded ? <ChevronDown className="w-3.5 h-3.5 text-[#FFC107]" /> : <ChevronRight className="w-3.5 h-3.5" />}
                      </td>
                      <td className="py-2 px-3 text-[#E2E8F0] whitespace-nowrap">{timeStr}</td>
                      <td className="py-2 px-3 text-[#FFC107] font-medium max-w-xs truncate" title={ev.topic}>
                        {ev.topic}
                      </td>
                      <td className="py-2 px-3 text-[#94A3B8] whitespace-nowrap">
                        <span className="px-1.5 py-0.5 rounded bg-[#0B0B0C] border border-[#1E293B] text-[10px]">
                          {ev.publisher || 'n/a'}
                        </span>
                      </td>
                      <td className="py-2 px-3 text-[#94A3B8] max-w-md truncate">
                        {typeof ev.payload === 'object' && ev.payload !== null
                          ? JSON.stringify(ev.payload)
                          : String(ev.payload)}
                      </td>
                      <td className="py-2 px-3 text-right">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            jumpToTopicInTree(ev.topic);
                          }}
                          className="p-1 hover:bg-[#334155] rounded text-[#64748B] hover:text-[#FFC107] transition-colors cursor-pointer"
                          title="Jump to topic in hierarchy"
                        >
                          <ExternalLink className="w-3 h-3" />
                        </button>
                      </td>
                    </tr>

                    {/* Expanded Payload Row */}
                    {isExpanded && (
                      <tr className="bg-[#0B0B0C]">
                        <td colSpan={6} className="p-3">
                          <div className="pl-6 space-y-2">
                            <JsonViewer data={ev.payload} title={`RECORD PAYLOAD • ${ev.id}`} maxHeight="max-h-52" />
                            {ev.properties && Object.keys(ev.properties).length > 0 && (
                              <div className="text-[10px] text-[#94A3B8] flex items-center gap-2">
                                <span className="font-semibold text-[#F8FAFC]">Properties:</span>
                                <span>{JSON.stringify(ev.properties)}</span>
                              </div>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination Status Notice (Phase 3 requirement: Schema limitation today) */}
      <div className="p-2.5 bg-[#0B0B0C] border-t border-[#1E293B] flex items-center justify-between text-[10px] font-mono text-[#64748B]">
        <div className="flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-[#FFC107]" />
          <span>Pagination: Backend GraphQL schema returns single query batch (Pagination blocked pending GraphQL schema)</span>
        </div>
        <span>Total loaded: {events.length} rows</span>
      </div>
    </div>
  );
};

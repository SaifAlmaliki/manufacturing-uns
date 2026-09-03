import React, { useState } from 'react';
import { Download, ChevronDown, ChevronRight, Search, FileSpreadsheet, ExternalLink, Lock } from 'lucide-react';
import { HistoricEvent } from '../../types/uns';
import { JsonViewer } from '../common/JsonViewer';
import { useUNS } from '../../context/UNSContext';
import { useAuth } from '../../context/AuthContext';
import { BtnSecondary, ConsoleCard } from '../ui/console-ui';

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

  const filteredEvents = events.filter((ev) => {
    if (!filterText) return true;
    const q = filterText.toLowerCase();
    return (
      ev.topic.toLowerCase().includes(q) ||
      (ev.publisher && ev.publisher.toLowerCase().includes(q)) ||
      JSON.stringify(ev.payload).toLowerCase().includes(q)
    );
  });

  const handleExportCsv = () => {
    if (!canExport || events.length === 0) return;

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
    <ConsoleCard id="historian-table-container" padding="none" className="flex flex-col overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-zinc-800 px-3 py-2">
        <div className="flex items-center gap-2">
          <FileSpreadsheet className="size-4 text-emerald-400" />
          <span className="text-xs font-semibold text-white">Historical Records</span>
          <span className="rounded-md bg-zinc-800 px-1.5 py-0.5 text-[10px] font-medium tabular-nums text-zinc-400">
            {filteredEvents.length} / {events.length} rows
          </span>
        </div>

        <div className="flex items-center gap-2">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-zinc-500" />
            <input
              type="search"
              placeholder="Search table…"
              value={filterText}
              onChange={(e) => setFilterText(e.target.value)}
              className="w-40 rounded-lg border-0 bg-zinc-800/60 py-1.5 pl-8 pr-2 text-xs text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:ring-1 focus:ring-[#FF7A00]/40 sm:w-52"
            />
          </div>

          <BtnSecondary
            id="export-historian-csv-btn"
            onClick={handleExportCsv}
            disabled={!canExport || events.length === 0}
            className="px-2.5 py-1.5 text-xs"
            title={canExport ? 'Export loaded historical rows to CSV' : 'Export CSV permission restricted by Administrator'}
          >
            {canExport ? <Download className="size-3.5" /> : <Lock className="size-3.5 text-rose-400" />}
            Export CSV
          </BtnSecondary>
        </div>
      </div>

      <div className="max-h-[420px] overflow-x-auto">
        <table className="w-full text-left font-mono text-[11px]">
          <thead className="sticky top-0 z-10 border-b border-zinc-800 bg-[#111114] text-[10px] uppercase tracking-wider text-zinc-500">
            <tr>
              <th className="w-8 px-3 py-2"></th>
              <th className="px-3 py-2">Timestamp</th>
              <th className="px-3 py-2">Topic</th>
              <th className="px-3 py-2">Publisher</th>
              <th className="px-3 py-2">Payload Summary</th>
              <th className="px-3 py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800">
            {isLoading ? (
              <tr>
                <td colSpan={6} className="py-12 text-center text-zinc-500">
                  <div className="mb-2 inline-block size-5 animate-spin rounded-full border-t-2 border-b-2 border-[#FF7A00]"></div>
                  <p>Querying Timescale historian records...</p>
                </td>
              </tr>
            ) : filteredEvents.length === 0 ? (
              <tr>
                <td colSpan={6} className="py-8 text-center text-zinc-500">
                  <p>No historical records match the selected query criteria.</p>
                  <p className="mt-1 text-[10px] text-zinc-600">Try the &quot;all&quot; time range or verify Timescale ingestion is running.</p>
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
                      className={`cursor-pointer transition-colors hover:bg-zinc-800/40 ${
                        isExpanded ? 'bg-zinc-800/60' : ''
                      }`}
                    >
                      <td className="px-3 py-2 text-zinc-500">
                        {isExpanded ? <ChevronDown className="size-3.5 text-[#FF7A00]" /> : <ChevronRight className="size-3.5" />}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-zinc-200">{timeStr}</td>
                      <td className="max-w-xs truncate px-3 py-2 font-medium text-[#FF7A00]" title={ev.topic}>
                        {ev.topic}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-zinc-400">
                        <span className="rounded border border-zinc-800 bg-zinc-900 px-1.5 py-0.5 text-[10px]">
                          {ev.publisher || 'n/a'}
                        </span>
                      </td>
                      <td className="max-w-md truncate px-3 py-2 text-zinc-400">
                        {typeof ev.payload === 'object' && ev.payload !== null
                          ? JSON.stringify(ev.payload)
                          : String(ev.payload)}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            jumpToTopicInTree(ev.topic);
                          }}
                          className="rounded p-1 text-zinc-500 transition-colors hover:bg-zinc-800 hover:text-[#FF7A00]"
                          title="Jump to topic in hierarchy"
                        >
                          <ExternalLink className="size-3" />
                        </button>
                      </td>
                    </tr>

                    {isExpanded && (
                      <tr className="bg-zinc-950/60">
                        <td colSpan={6} className="p-3">
                          <div className="space-y-2 pl-6">
                            <JsonViewer data={ev.payload} title={`RECORD PAYLOAD • ${ev.id}`} maxHeight="max-h-52" />
                            {ev.properties && Object.keys(ev.properties).length > 0 && (
                              <div className="flex items-center gap-2 text-[10px] text-zinc-500">
                                <span className="font-semibold text-zinc-200">Properties:</span>
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

      <div className="flex items-center justify-between border-t border-zinc-800 px-3 py-2 font-mono text-[10px] text-zinc-500">
        <div className="flex items-center gap-1.5">
          <span className="size-1.5 rounded-full bg-[#FF7A00]" />
          <span>Pagination: Backend GraphQL schema returns single query batch (Pagination blocked pending GraphQL schema)</span>
        </div>
        <span>Total loaded: {events.length} rows</span>
      </div>
    </ConsoleCard>
  );
};

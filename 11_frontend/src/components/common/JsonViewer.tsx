import React, { useState } from 'react';
import { Copy, Check, Code, FileText, Search } from 'lucide-react';

interface JsonViewerProps {
  data: unknown;
  title?: string;
  maxHeight?: string;
  initialExpanded?: boolean;
}

export const JsonViewer: React.FC<JsonViewerProps> = ({
  data,
  title,
  maxHeight = 'max-h-96',
}) => {
  const [copied, setCopied] = useState(false);
  const [viewMode, setViewMode] = useState<'formatted' | 'raw'>('formatted');
  const [searchTerm, setSearchTerm] = useState('');

  const jsonString = typeof data === 'string' ? data : JSON.stringify(data, null, 2);

  const handleCopy = () => {
    navigator.clipboard.writeText(jsonString);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const renderSyntaxHighlighted = (json: string) => {
    if (!json) return <span className="text-[#64748B] italic font-mono text-[10px]">null</span>;

    const lines = json.split('\n');
    return lines.map((line, idx) => {
      const isSearchMatch = searchTerm && line.toLowerCase().includes(searchTerm.toLowerCase());

      const formattedLine = line.replace(
        /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)/g,
        (match) => {
          let cls = 'text-amber-600 dark:text-[#FFC107] font-semibold'; // number default amber
          if (/^"/.test(match)) {
            if (/:$/.test(match)) {
              cls = 'text-sky-700 dark:text-[#38BDF8] font-semibold'; // key cyan/sky
            } else {
              cls = 'text-emerald-700 dark:text-[#10B981]'; // string value emerald
            }
          } else if (/true|false/.test(match)) {
            cls = 'text-purple-700 dark:text-[#A855F7] font-bold'; // boolean
          } else if (/null/.test(match)) {
            cls = 'text-[#64748B] italic'; // null
          }
          return `<span class="${cls}">${match}</span>`;
        }
      );

      return (
        <div
          key={idx}
          className={`flex hover:bg-slate-100 dark:hover:bg-[#1E293B]/40 px-2 py-0.2 font-mono text-[10px] leading-relaxed ${
            isSearchMatch ? 'bg-amber-100 dark:bg-amber-950/40 border-l-2 border-amber-500 dark:border-[#FFC107]' : ''
          }`}
        >
          <span className="w-7 select-none text-right pr-2 text-slate-400 dark:text-[#475569] font-mono text-[9px]">{idx + 1}</span>
          <span className="flex-1 overflow-x-auto whitespace-pre text-slate-800 dark:text-slate-200" dangerouslySetInnerHTML={{ __html: formattedLine }} />
        </div>
      );
    });
  };

  return (
    <div id="json-viewer-container" className="flex flex-col bg-white dark:bg-[#0B0B0C] border border-[#E2E8F0] dark:border-[#1E293B] rounded-lg overflow-hidden shadow-xs">
      {/* Header bar */}
      <div className="flex items-center justify-between px-2.5 py-1.5 bg-[#F8FAFC] dark:bg-[#111114] border-b border-[#E2E8F0] dark:border-[#1E293B] text-[10px]">
        <div className="flex items-center gap-2">
          <Code className="w-3.5 h-3.5 text-amber-600 dark:text-[#FFC107]" />
          <span className="font-semibold text-[#0F172A] dark:text-[#F8FAFC] tracking-wider uppercase font-mono">{title || 'PAYLOAD'}</span>
          {typeof data === 'object' && data !== null && (
            <span className="px-1.5 py-0.2 text-[9px] rounded bg-slate-200 dark:bg-[#1E293B] text-[#475569] dark:text-[#94A3B8] font-mono border border-slate-300 dark:border-[#334155] font-semibold">
              {Array.isArray(data) ? `${data.length} items` : `${Object.keys(data).length} keys`}
            </span>
          )}
        </div>

        <div className="flex items-center gap-1.5">
          {/* Search inside JSON */}
          <div className="relative flex items-center">
            <Search className="w-3 h-3 text-[#64748B] absolute left-1.5 pointer-events-none" />
            <input
              type="text"
              placeholder="Find..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="bg-white dark:bg-[#0B0B0C] border border-[#CBD5E1] dark:border-[#1E293B] text-[10px] font-mono rounded pl-5 pr-1.5 py-0.5 text-[#0F172A] dark:text-[#F8FAFC] placeholder-[#64748B] focus:outline-none focus:border-amber-500 dark:focus:border-[#FFC107] w-20 focus:w-28 transition-all"
            />
          </div>

          <button
            onClick={() => setViewMode(viewMode === 'formatted' ? 'raw' : 'formatted')}
            className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-white dark:bg-[#1E293B] hover:bg-slate-100 dark:hover:bg-[#334155] border border-[#CBD5E1] dark:border-[#334155] text-[9px] font-mono text-[#0F172A] dark:text-[#E2E8F0] transition-colors cursor-pointer"
            title="Toggle Raw / Formatted"
          >
            {viewMode === 'formatted' ? <FileText className="w-3 h-3 text-[#64748B]" /> : <Code className="w-3 h-3 text-amber-600 dark:text-[#FFC107]" />}
            <span>{viewMode === 'formatted' ? 'Raw' : 'Tree'}</span>
          </button>

          <button
            onClick={handleCopy}
            className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-white dark:bg-[#1E293B] hover:bg-slate-100 dark:hover:bg-[#334155] border border-[#CBD5E1] dark:border-[#334155] text-[9px] font-mono text-[#0F172A] dark:text-[#E2E8F0] transition-colors cursor-pointer"
            title="Copy payload to clipboard"
          >
            {copied ? <Check className="w-3 h-3 text-emerald-600 dark:text-[#10B981]" /> : <Copy className="w-3 h-3 text-[#64748B]" />}
            <span>{copied ? 'Copied' : 'Copy'}</span>
          </button>
        </div>
      </div>

      {/* Body */}
      <div className={`overflow-auto ${maxHeight} p-1 scrollbar-thin scrollbar-thumb-slate-300 dark:scrollbar-thumb-[#1E293B] bg-slate-50/50 dark:bg-[#0B0B0C]`}>
        {viewMode === 'formatted' ? (
          <div>{renderSyntaxHighlighted(jsonString)}</div>
        ) : (
          <textarea
            readOnly
            value={jsonString}
            className="w-full h-full min-h-[140px] bg-transparent text-[#0F172A] dark:text-[#E2E8F0] font-mono text-[10px] p-2 focus:outline-none resize-none"
          />
        )}
      </div>
    </div>
  );
};

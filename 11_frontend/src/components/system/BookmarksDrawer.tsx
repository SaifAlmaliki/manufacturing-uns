import React, { useState } from 'react';
import { Bookmark, X, Trash2, ExternalLink, History, Search } from 'lucide-react';
import { useUNS } from '../../context/UNSContext';

interface BookmarksDrawerProps {
  isOpen: boolean;
  onClose: () => void;
}

export const BookmarksDrawer: React.FC<BookmarksDrawerProps> = ({ isOpen, onClose }) => {
  const { bookmarks, removeBookmark, jumpToTopicInTree, jumpToHistorian } = useUNS();
  const [search, setSearch] = useState('');

  if (!isOpen) return null;

  const filtered = bookmarks.filter(
    (b) =>
      b.topic.toLowerCase().includes(search.toLowerCase()) ||
      (b.alias && b.alias.toLowerCase().includes(search.toLowerCase()))
  );

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-black/70 backdrop-blur-xs flex justify-end">
      <div className="w-full max-w-md bg-[#111114] border-l border-[#1E293B] h-full flex flex-col shadow-2xl animate-in slide-in-from-right duration-200">
        {/* Header */}
        <div className="p-3.5 bg-[#111114] border-b border-[#1E293B] flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Bookmark className="w-4 h-4 text-[#FFC107]" />
            <span className="font-bold text-[#F8FAFC] text-xs uppercase tracking-wider">Topic Bookmarks</span>
            <span className="px-1.5 py-0.2 rounded bg-[#0B0B0C] border border-[#1E293B] text-[#FFC107] text-[10px] font-mono font-bold">
              {bookmarks.length}
            </span>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded bg-[#0B0B0C] border border-[#1E293B] hover:bg-[#1E293B] text-[#64748B] hover:text-[#F8FAFC] cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Search */}
        <div className="p-3 border-b border-[#1E293B] bg-[#0B0B0C]">
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-[#64748B] absolute left-2.5 top-2 pointer-events-none" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Filter bookmarks..."
              className="w-full bg-[#111114] border border-[#1E293B] rounded pl-8 pr-2 py-1 text-[11px] text-[#F8FAFC] font-mono focus:outline-none focus:border-[#FFC107]"
            />
          </div>
        </div>

        {/* List */}
        <div className="flex-1 overflow-y-auto p-3 space-y-2 font-mono text-xs bg-[#050505] scrollbar-thin scrollbar-thumb-[#1E293B]">
          {filtered.length === 0 ? (
            <div className="text-center py-12 text-[#64748B]">
              <Bookmark className="w-8 h-8 mx-auto mb-2 text-[#1E293B]" />
              <p className="text-[#94A3B8]">No saved bookmarks found.</p>
              <p className="text-[10px] mt-1 text-[#64748B]">Bookmark any topic from the hierarchy or payload view.</p>
            </div>
          ) : (
            filtered.map((b) => (
              <div
                key={b.topic}
                className="p-3 rounded bg-[#111114] border border-[#1E293B] hover:border-[#334155] space-y-1.5 transition-colors"
              >
                <div className="flex items-center justify-between">
                  <span className="font-semibold text-[#FFC107] truncate max-w-xs text-xs">{b.alias || b.topic}</span>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => {
                        jumpToHistorian(b.topic);
                        onClose();
                      }}
                      className="p-1 hover:bg-[#1E293B] text-[#94A3B8] hover:text-[#FFC107] rounded cursor-pointer"
                      title="Open in Historian"
                    >
                      <History className="w-3.5 h-3.5" />
                    </button>
                    <button
                      onClick={() => {
                        jumpToTopicInTree(b.topic);
                        onClose();
                      }}
                      className="p-1 hover:bg-[#1E293B] text-[#94A3B8] hover:text-[#FFC107] rounded cursor-pointer"
                      title="Locate in Tree"
                    >
                      <ExternalLink className="w-3.5 h-3.5" />
                    </button>
                    <button
                      onClick={() => removeBookmark(b.topic)}
                      className="p-1 hover:bg-[#1E293B] text-[#64748B] hover:text-rose-400 rounded cursor-pointer"
                      title="Delete Bookmark"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>

                <div className="text-[10px] text-[#94A3B8] break-all">{b.topic}</div>
                <div className="text-[9px] text-[#64748B]">Saved: {new Date(b.addedAt).toLocaleDateString()}</div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};

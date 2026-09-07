import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { Loader2, Send, Trash2, X } from 'lucide-react';
import { useUNS } from '../../context/UNSContext';
import { useAlarms } from '../../context/AlarmContext';
import {
  CopilotAuthError,
  CopilotUnavailableError,
  checkCopilotHealth,
  createConversation,
  deleteConversation,
  getConversation,
  listConversations,
  sendChat,
  type CopilotCitation,
  type CopilotConversation,
  type CopilotMessage,
} from './copilotApi';
import { contextChip, pageContext } from './copilotContext';
import { citationTarget } from './citationJump';
import { JOB_CARDS } from './jobCards';

interface FactoryCopilotDrawerProps {
  isOpen: boolean;
  onClose: () => void;
}

type LampState = 'idle' | 'busy' | 'down';

export const FactoryCopilotDrawer: React.FC<FactoryCopilotDrawerProps> = ({ isOpen, onClose }) => {
  const location = useLocation();
  const { selectedNode, copilotMetricKey, jumpToHistorian, jumpToTopicInTree } = useUNS();
  const { focusedAlarmTopic } = useAlarms();

  const [threads, setThreads] = useState<CopilotConversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<CopilotMessage[]>([]);
  const [draft, setDraft] = useState('');
  const [lamp, setLamp] = useState<LampState>('idle');
  const [unavailable, setUnavailable] = useState(false);
  const composerRef = useRef<HTMLTextAreaElement>(null);

  const ctx = useMemo(
    () =>
      pageContext({
        pathname: location.pathname,
        selectedTopic: selectedNode?.topic,
        selectedMetricKey: copilotMetricKey,
        selectedAlarmTopic: focusedAlarmTopic,
      }),
    [location.pathname, selectedNode?.topic, copilotMetricKey, focusedAlarmTopic],
  );

  const chip = contextChip(ctx);

  const loadThreads = useCallback(async () => {
    try {
      const rows = await listConversations();
      setThreads(rows);
    } catch (err) {
      if (!(err instanceof CopilotUnavailableError)) {
        // Auth or other errors should not block the composer when health is ok.
        return;
      }
    }
  }, []);

  const openThread = useCallback(async (id: string) => {
    try {
      const row = await getConversation(id);
      setActiveId(id);
      setMessages(row.messages);
    } catch (err) {
      if (err instanceof CopilotUnavailableError) {
        setUnavailable(true);
      }
    }
  }, []);

  useEffect(() => {
    if (!isOpen) return;
    void loadThreads();
    void checkCopilotHealth().then((ok) => {
      setUnavailable(!ok);
    });
  }, [isOpen, loadThreads]);

  useEffect(() => {
    if (!isOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isOpen, onClose]);

  const ensureConversation = async (): Promise<string | null> => {
    if (activeId) return activeId;
    try {
      const conv = await createConversation();
      setActiveId(conv.id);
      setThreads((prev) => [conv, ...prev]);
      setMessages([]);
      return conv.id;
    } catch (err) {
      if (err instanceof CopilotUnavailableError) setUnavailable(true);
      return null;
    }
  };

  const handleSend = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || lamp === 'busy') return;
    const conversationId = await ensureConversation();
    if (!conversationId) return;

    setLamp('busy');
    setMessages((prev) => [...prev, { role: 'user', body: trimmed, citations: [] }]);
    setDraft('');

    try {
      const result = await sendChat({
        message: trimmed,
        conversationId,
        context: ctx,
      });
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', body: result.text, citations: result.citations },
      ]);
      setUnavailable(false);
      void loadThreads();
    } catch (err) {
      const message =
        err instanceof CopilotAuthError
          ? 'Sign in again to use Factory Copilot.'
          : err instanceof CopilotUnavailableError
            ? 'Factory Copilot is unavailable.'
            : err instanceof Error
              ? err.message
              : 'Factory Copilot could not send that message.';
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          body: message,
          citations: [],
        },
      ]);
    } finally {
      setLamp('idle');
    }
  };

  const handleNewChat = async () => {
    const conv = await createConversation();
    if (!conv) return;
    setActiveId(conv.id);
    setMessages([]);
    setThreads((prev) => [conv, ...prev]);
  };

  const handleDelete = async (id: string) => {
    await deleteConversation(id);
    setThreads((prev) => prev.filter((t) => t.id !== id));
    if (activeId === id) {
      setActiveId(null);
      setMessages([]);
    }
  };

  const handleCitationClick = (citation: CopilotCitation) => {
    const hash = citationTarget(citation.source);
    window.location.hash = hash;
    if (citation.source === 'historian' && citation.topic) {
      jumpToHistorian(citation.topic);
    } else if (citation.topic) {
      jumpToTopicInTree(citation.topic);
    }
  };

  if (!isOpen) return null;

  const lampState: LampState = unavailable ? 'down' : lamp;

  return (
    <div className="fixed inset-0 z-50 flex justify-end overflow-hidden bg-black/70 backdrop-blur-xs">
      <div className="instrument-grain flex h-full w-full max-w-3xl border-l border-border bg-background shadow-2xl">
        {/* History rail */}
        <aside className="flex w-44 shrink-0 flex-col border-r border-border bg-surface">
          <div className="border-b border-border p-3">
            <button
              type="button"
              onClick={() => void handleNewChat()}
              className="font-heading w-full border border-[#FF7A00]/40 px-2 py-1.5 text-left text-xs font-semibold tracking-wide text-[#FF7A00] hover:bg-muted"
            >
              New chat +
            </button>
          </div>
          <div className="flex-1 overflow-y-auto p-2 space-y-1">
            {threads.map((thread) => (
              <div
                key={thread.id}
                className={`group flex items-start gap-1 border px-2 py-1.5 text-[10px] ${
                  activeId === thread.id
                    ? 'border-[#FF7A00]/50 bg-muted'
                    : 'border-border bg-background hover:bg-muted'
                }`}
              >
                <button
                  type="button"
                  className="min-w-0 flex-1 text-left"
                  onClick={() => void openThread(thread.id)}
                >
                  <div className="truncate font-heading text-[11px] text-foreground">{thread.title}</div>
                  <div className="font-mono text-[9px] text-muted-foreground tabular-nums">
                    {new Date(thread.updatedAt).toLocaleString()}
                  </div>
                </button>
                <button
                  type="button"
                  aria-label={`Delete ${thread.title}`}
                  className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-red-400"
                  onClick={() => void handleDelete(thread.id)}
                >
                  <Trash2 className="size-3" />
                </button>
              </div>
            ))}
          </div>
        </aside>

        {/* Main bay */}
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex items-center justify-between border-b border-border px-4 py-3">
            <div>
              <div className="flex items-center gap--2">
                <span
                  data-testid="copilot-lamp"
                  data-state={lampState}
                  className={`inline-block h-[10px] w-[10px] border-2 border-[#FF7A00] ${
                    lampState === 'busy' ? 'animate-pulse bg-[#FF7A00]' : lampState === 'down' ? 'bg-red-500 border-red-500' : 'bg-transparent'
                  }`}
                />
                <span className="font-heading text-xs font-bold tracking-[0.25em] text-foreground">
                  FACTORY COPILOT
                </span>
              </div>
              <p
                data-testid="copilot-context"
                className="mt-1 font-mono text-[10px] text-muted-foreground truncate"
              >
                {chip}
              </p>
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close Factory Copilot"
              className="flex size-8 items-center justify-center border border-border bg-surface text-muted-foreground hover:text-foreground"
            >
              <X className="size-4" />
            </button>
          </header>

          <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
            {unavailable && messages.length === 0 && (
              <p className="font-heading text-sm text-muted-foreground">Factory Copilot is unavailable.</p>
            )}

            {messages.length === 0 && !unavailable && (
              <div className="space-y-4">
                <p className="font-heading text-sm text-foreground">
                  Hello, how can I help you today?
                </p>
                <p className="font-mono text-[10px] text-muted-foreground">
                  Try one of these to get started:
                </p>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {JOB_CARDS.map((card) => (
                    <button
                      key={card.id}
                      type="button"
                      role="button"
                      className="border border-border bg-surface px-3 py-3 text-left font-heading text-xs text-foreground hover:border-[#FF7A00]/50"
                      onClick={() => void handleSend(card.prompt)}
                    >
                      {card.prompt}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((msg, index) => (
              <div
                key={`${msg.role}-${index}`}
                className={
                  msg.role === 'assistant'
                    ? 'max-w-[90%] border-l-2 border-[#FF7A00] pl-3 font-heading text-sm text-foreground'
                    : 'ml-auto max-w-[85%] border border-border bg-surface px-3 py-2 text-sm text-muted-foreground'
                }
              >
                <p className="whitespace-pre-wrap">{msg.body}</p>
                {msg.citations.length > 0 && (
                  <div className="mt-2 space-y-1">
                    {msg.citations.map((citation, ci) => (
                      <button
                        key={`${citation.topic}-${ci}`}
                        type="button"
                        data-testid="copilot-citation"
                        className="block w-full border border-border bg-background px-2 py-1 text-left font-mono text-[10px] text-[#FF7A00] hover:bg-muted"
                        onClick={() => handleCitationClick(citation)}
                      >
                        {citation.asset || citation.topic} · {citation.source} · {citation.time}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ))}

            {lamp === 'busy' && (
              <div className="flex items-center gap-2 text-muted-foreground">
                <Loader2 className="size-4 animate-spin" />
                <span className="font-mono text-xs">Looking…</span>
              </div>
            )}
          </div>

          <footer className="border-t border-border p-3">
            <div className="flex gap-2">
              <textarea
                ref={composerRef}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="Message Factory Copilot..."
                rows={2}
                disabled={lamp === 'busy' || unavailable}
                className="min-h-[44px] flex-1 resize-none border border-border bg-surface px-3 py-2 font-heading text-sm text-foreground focus:outline-none focus:border-[#FF7A00]/60 disabled:opacity-50"
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    void handleSend(draft);
                  }
                }}
              />
              <button
                type="button"
                aria-label="Send message"
                disabled={lamp === 'busy' || unavailable || !draft.trim()}
                className="flex size-11 shrink-0 items-center justify-center border border-[#FF7A00] bg-[#FF7A00]/10 text-[#FF7A00] disabled:opacity-40"
                onClick={() => void handleSend(draft)}
              >
                <Send className="size-4" />
              </button>
            </div>
          </footer>
        </div>
      </div>
    </div>
  );
};

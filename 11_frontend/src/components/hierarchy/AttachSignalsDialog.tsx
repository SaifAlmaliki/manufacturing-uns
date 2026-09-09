import { useEffect, useMemo, useState } from 'react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { filterSubscribedSignals } from '../../lib/connectivity/signal-filters';
import { unsGraphQLClient } from '../../services/graphql/client';
import type { GraphqlSubscribedSignal } from '../../services/graphql/types';
import { BtnPrimary, ConsoleInput } from '../ui/console-ui';

export function signalKey(row: Pick<GraphqlSubscribedSignal, 'serverId' | 'nodeId'>): string {
  return `${row.serverId}\n${row.nodeId}`;
}

function attachedKeys(signals: GraphqlSubscribedSignal[], prefix: string): Set<string> {
  return new Set(signals.filter((signal) => signal.assetPath === prefix).map(signalKey));
}

export function AttachSignalsDialog({
  open,
  nodeLabel,
  prefix,
  assetId,
  signals,
  onClose,
  onSignalsChange,
}: {
  open: boolean;
  nodeLabel: string;
  prefix: string;
  assetId: number | null;
  signals: GraphqlSubscribedSignal[];
  onClose: () => void;
  onSignalsChange: (next: GraphqlSubscribedSignal[]) => void;
}) {
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setSearch('');
    setError(null);
    setSelected(attachedKeys(signals, prefix));
  }, [open, prefix, signals]);

  const visible = useMemo(
    () => filterSubscribedSignals(signals, { search }),
    [signals, search],
  );
  const canAttach = assetId != null;

  const toggle = (key: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const handleSave = async () => {
    if (assetId == null) return;
    const current = attachedKeys(signals, prefix);
    const toAttach = signals.filter((signal) => {
      const key = signalKey(signal);
      return selected.has(key) && !current.has(key);
    });
    const toDetach = signals.filter((signal) => {
      const key = signalKey(signal);
      return current.has(key) && !selected.has(key);
    });
    if (toAttach.length === 0 && toDetach.length === 0) {
      onClose();
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const updated = await Promise.all([
        ...toAttach.map((signal) =>
          unsGraphQLClient.updateConnectivityTag(signal.serverId, signal.nodeId, { assetId }),
        ),
        ...toDetach.map((signal) =>
          unsGraphQLClient.updateConnectivityTag(signal.serverId, signal.nodeId, { assetId: null }),
        ),
      ]);
      const byKey = new Map(updated.map((tag) => [signalKey(tag), tag]));
      onSignalsChange(
        signals.map((signal) => {
          const next = byKey.get(signalKey(signal));
          return next ? { ...signal, ...next } : signal;
        }),
      );
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Signals were not attached');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent
        aria-label={`Attach signals to ${nodeLabel}`}
        showCloseButton={false}
        className="instrument-panel instrument-grain border-[#FF7A00]/20 sm:max-w-lg"
      >
        <DialogHeader>
          <DialogTitle className="font-heading text-lg">Attach signals to {nodeLabel}</DialogTitle>
          <DialogDescription>
            Link subscribed signals to this plant node — the same Asset assignment as Assets &
            Connectivity.
          </DialogDescription>
        </DialogHeader>
        {!canAttach && (
          <p className="text-xs text-rose-400">
            This node is not in the Asset Model yet. Save the plant hierarchy first, then attach
            signals.
          </p>
        )}
        {error && (
          <p className="rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
            {error}
          </p>
        )}
        <ConsoleInput
          aria-label="Filter signals"
          placeholder="Filter signals…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <div className="max-h-64 space-y-1 overflow-y-auto">
          {visible.length === 0 ? (
            <p className="px-1 py-4 text-xs text-muted-foreground">No subscribed signals.</p>
          ) : (
            visible.map((signal) => {
              const key = signalKey(signal);
              const elsewhere =
                signal.assetPath && signal.assetPath !== prefix ? signal.assetPath : null;
              return (
                <label
                  key={key}
                  className="flex cursor-pointer items-start gap-2 rounded-md px-2 py-1.5 hover:bg-muted"
                >
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={selected.has(key)}
                    onChange={() => toggle(key)}
                    aria-label={signal.displayName}
                    disabled={!canAttach || saving}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-foreground">
                      {signal.displayName}
                    </span>
                    <span className="block truncate font-mono text-[11px] text-muted-foreground">
                      {signal.mqttTopic}
                    </span>
                    {elsewhere ? (
                      <span className="block truncate text-[11px] text-muted-foreground">
                        Now on {elsewhere}
                      </span>
                    ) : null}
                  </span>
                </label>
              );
            })
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <BtnPrimary onClick={() => void handleSave()} disabled={!canAttach || saving}>
            {saving ? 'Attaching…' : 'Attach'}
          </BtnPrimary>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

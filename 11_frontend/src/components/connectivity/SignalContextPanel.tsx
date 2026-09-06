import React, { useEffect, useState } from 'react';
import { unsGraphQLClient } from '../../services/graphql/client';
import type { GraphqlSubscribedSignal } from '../../services/graphql/types';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

type SignalContextPanelProps = {
  signal: GraphqlSubscribedSignal;
  onClose: () => void;
  onUpdated: (next: GraphqlSubscribedSignal) => void;
  onUnsubscribed: (serverId: string, nodeId: string) => void;
};

export const SignalContextPanel: React.FC<SignalContextPanelProps> = ({
  signal,
  onClose,
  onUpdated,
  onUnsubscribed,
}) => {
  const [name, setName] = useState(signal.displayName);
  const [topic, setTopic] = useState(signal.mqttTopic);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [confirmUnsub, setConfirmUnsub] = useState(false);
  const [unsubscribing, setUnsubscribing] = useState(false);

  useEffect(() => {
    setName(signal.displayName);
    setTopic(signal.mqttTopic);
    setSaveError(null);
    setConfirmUnsub(false);
  }, [signal.serverId, signal.nodeId, signal.displayName, signal.mqttTopic]);

  const handleSave = async () => {
    const displayName = name.trim();
    const mqttTopic = topic.trim();
    if (!mqttTopic) {
      setSaveError('Topic is required.');
      return;
    }
    if (!displayName) {
      setSaveError('Name is required.');
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      const updated = await unsGraphQLClient.updateConnectivityTag(signal.serverId, signal.nodeId, {
        displayName,
        mqttTopic,
      });
      onUpdated({ ...signal, ...updated, serverName: signal.serverName });
      onClose();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Signal was not saved');
    } finally {
      setSaving(false);
    }
  };

  const handleUnsubscribe = async () => {
    setUnsubscribing(true);
    setSaveError(null);
    try {
      await unsGraphQLClient.unsubscribeConnectivityTag(signal.serverId, signal.nodeId);
      onUnsubscribed(signal.serverId, signal.nodeId);
      onClose();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Unsubscribe failed');
      setConfirmUnsub(false);
    } finally {
      setUnsubscribing(false);
    }
  };

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        aria-label="Signal context"
        showCloseButton={false}
        className="instrument-panel instrument-grain gap-4 border-[#FF7A00]/20 sm:max-w-md"
      >
        <DialogHeader>
          <p className="text-[10px] font-medium uppercase tracking-[0.22em] text-[#FF7A00]">
            Subscribed signal
          </p>
          <DialogTitle className="font-heading text-lg">{signal.displayName}</DialogTitle>
          <DialogDescription>
            Edit the published name and topic. Unsubscribe removes it from Signals and Condition
            Monitoring.
          </DialogDescription>
        </DialogHeader>

        {saveError && (
          <div className="rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
            {saveError}
          </div>
        )}

        <div className="grid gap-3">
          <div className="grid gap-1.5">
            <Label htmlFor="signal-ctx-name">Name</Label>
            <Input
              id="signal-ctx-name"
              aria-label="Name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="signal-ctx-topic">Topic</Label>
            <Input
              id="signal-ctx-topic"
              aria-label="Topic"
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              className="font-mono text-xs"
            />
          </div>
          <p className="font-mono text-[10px] text-muted-foreground">{signal.nodeId}</p>
        </div>

        <DialogFooter className="gap-2 sm:justify-between">
          {confirmUnsub ? (
            <>
              <p className="self-center text-xs text-muted-foreground">Unsubscribe this signal?</p>
              <div className="flex gap-2">
                <Button variant="outline" onClick={() => setConfirmUnsub(false)}>
                  Cancel
                </Button>
                <Button
                  onClick={() => void handleUnsubscribe()}
                  disabled={unsubscribing}
                  aria-label="Confirm"
                >
                  {unsubscribing ? 'Unsubscribing…' : 'Confirm'}
                </Button>
              </div>
            </>
          ) : (
            <>
              <Button
                variant="outline"
                className="text-rose-400 hover:text-rose-300"
                onClick={() => setConfirmUnsub(true)}
              >
                Unsubscribe
              </Button>
              <div className="flex gap-2">
                <Button variant="outline" onClick={onClose}>
                  Cancel
                </Button>
                <Button onClick={() => void handleSave()} disabled={saving} aria-label="Save">
                  {saving ? 'Saving…' : 'Save'}
                </Button>
              </div>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

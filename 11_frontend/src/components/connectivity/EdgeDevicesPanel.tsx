import React, { useMemo, useState } from 'react';
import { Activity, CheckCircle2, KeyRound, Plus, Shield, UserPlus } from 'lucide-react';
import type { GraphqlEdgeDevice } from '../../services/graphql/types';
import { unsGraphQLClient } from '../../services/graphql/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  BtnGhost,
  BtnPrimary,
  BtnSecondary,
  CompactKpiRow,
  ConsoleCard,
  ConsoleSelect,
  PageStat,
} from '../ui/console-ui';
import {
  edgeConnectionState,
  edgePhaseDotClass,
  edgePhaseLabel,
  revisionLagLabel,
} from '../../lib/connectivity/edge-status';

export type EdgeDevicesPanelProps = {
  edges: GraphqlEdgeDevice[];
  selectedEdgeId: string | null;
  onSelectEdge: (edgeId: string) => void;
  onEdgesChange: (edges: GraphqlEdgeDevice[]) => void;
  isAdmin: boolean;
  simulationHint?: string | null;
};

export const EdgeDevicesPanel: React.FC<EdgeDevicesPanelProps> = ({
  edges,
  selectedEdgeId,
  onSelectEdge,
  onEdgesChange,
  isAdmin,
  simulationHint,
}) => {
  const [registerOpen, setRegisterOpen] = useState(false);
  const [newEdgeId, setNewEdgeId] = useState('');
  const [newDisplayName, setNewDisplayName] = useState('');
  const [panelError, setPanelError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [tokenEdgeId, setTokenEdgeId] = useState<string | null>(null);
  const [enrollmentToken, setEnrollmentToken] = useState<string | null>(null);
  const [grantUserId, setGrantUserId] = useState('');
  const [grantEdgeId, setGrantEdgeId] = useState('');

  const selected = useMemo(
    () => edges.find((edge) => edge.edgeId === selectedEdgeId) ?? edges[0] ?? null,
    [edges, selectedEdgeId],
  );

  const openEnrollment = async (edgeId: string) => {
    setPanelError(null);
    setBusy(true);
    try {
      const token = await unsGraphQLClient.createEdgeEnrollmentToken(edgeId);
      setTokenEdgeId(edgeId);
      setEnrollmentToken(token);
    } catch (err) {
      setPanelError(err instanceof Error ? err.message : 'Enrollment token was not created');
    } finally {
      setBusy(false);
    }
  };

  const closeEnrollment = () => {
    setTokenEdgeId(null);
    setEnrollmentToken(null);
  };

  const handleRegister = async () => {
    setPanelError(null);
    setBusy(true);
    try {
      const device = await unsGraphQLClient.registerEdgeDevice(
        newEdgeId.trim(),
        newDisplayName.trim() || newEdgeId.trim(),
      );
      const next = [...edges.filter((edge) => edge.edgeId !== device.edgeId), device].sort((a, b) =>
        a.edgeId.localeCompare(b.edgeId),
      );
      onEdgesChange(next);
      onSelectEdge(device.edgeId);
      setRegisterOpen(false);
      setNewEdgeId('');
      setNewDisplayName('');
    } catch (err) {
      setPanelError(err instanceof Error ? err.message : 'Edge was not registered');
    } finally {
      setBusy(false);
    }
  };

  const handleGrant = async () => {
    const edgeId = grantEdgeId || selected?.edgeId || '';
    if (!edgeId || !grantUserId.trim()) return;
    setPanelError(null);
    setBusy(true);
    try {
      await unsGraphQLClient.grantEdgeAccess(edgeId, grantUserId.trim());
      setGrantUserId('');
    } catch (err) {
      setPanelError(err instanceof Error ? err.message : 'Grant failed');
    } finally {
      setBusy(false);
    }
  };

  if (edges.length === 0) {
    return (
      <ConsoleCard padding="md" className="text-sm text-muted-foreground">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p>No edge devices registered yet. Admins enroll DMZ HiveMQ Edge VMs from here.</p>
          {isAdmin ? (
            <BtnPrimary onClick={() => setRegisterOpen(true)} className="px-3 py-1.5 text-xs">
              <Plus className="size-3.5" />
              Register edge
            </BtnPrimary>
          ) : null}
        </div>
        {panelError ? <p className="mt-2 text-xs text-rose-300">{panelError}</p> : null}
        <RegisterDialog
          open={registerOpen}
          onOpenChange={setRegisterOpen}
          edgeId={newEdgeId}
          displayName={newDisplayName}
          onEdgeIdChange={setNewEdgeId}
          onDisplayNameChange={setNewDisplayName}
          onSubmit={() => void handleRegister()}
          busy={busy}
        />
      </ConsoleCard>
    );
  }

  const connection = selected ? edgeConnectionState(selected) : 'offline';

  return (
    <div className="space-y-2">
      <CompactKpiRow
        actions={
          isAdmin ? (
            <>
              <BtnSecondary onClick={() => setRegisterOpen(true)} className="px-2.5 py-1.5 text-xs">
                <Plus className="size-3.5" />
                Register
              </BtnSecondary>
              {selected ? (
                <BtnSecondary
                  onClick={() => void openEnrollment(selected.edgeId)}
                  disabled={busy}
                  className="px-2.5 py-1.5 text-xs"
                  aria-label="Create enrollment token"
                >
                  <KeyRound className="size-3.5" />
                  Enroll
                </BtnSecondary>
              ) : null}
            </>
          ) : null
        }
      >
        <PageStat
          compact
          label="Edge"
          value={selected?.displayName ?? '—'}
          icon={<Shield className="size-3.5 text-[#FF7A00]" />}
        />
        <PageStat
          compact
          label="Heartbeat"
          value={connection === 'online' ? 'Online' : connection === 'revoked' ? 'Revoked' : 'Offline'}
          valueClassName={
            connection === 'online' ? 'text-emerald-400' : connection === 'revoked' ? 'text-rose-400' : 'text-amber-400'
          }
          icon={<Activity className="size-3.5 text-muted-foreground" />}
        />
        {selected ? (
          <>
            <PageStat
              compact
              label="Desired"
              value={selected.desiredRevision}
              icon={<span className={`size-2 rounded-full ${edgePhaseDotClass(selected.appliedPhase)}`} />}
            />
            <PageStat
              compact
              label="Applied"
              value={selected.appliedRevision}
              icon={<CheckCircle2 className="size-3.5 text-emerald-400" />}
            />
            <PageStat
              compact
              label="Phase"
              value={edgePhaseLabel(selected.appliedPhase)}
              valueClassName="text-xs"
              icon={<span className={`size-2 rounded-full ${edgePhaseDotClass(selected.appliedPhase)}`} />}
            />
            <PageStat
              compact
              label="Lag"
              value={revisionLagLabel(selected.desiredRevision, selected.appliedRevision)}
              icon={<Activity className="size-3.5 text-muted-foreground" />}
            />
          </>
        ) : null}
      </CompactKpiRow>

      <ConsoleCard padding="sm" className="flex flex-wrap items-center gap-2">
        <Label htmlFor="edge-select" className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
          Edge site
        </Label>
        <ConsoleSelect
          id="edge-select"
          aria-label="Edge site"
          value={selectedEdgeId ?? selected?.edgeId ?? ''}
          onChange={(event) => onSelectEdge(event.target.value)}
          className="min-w-[12rem]"
        >
          {edges.map((edge) => (
            <option key={edge.edgeId} value={edge.edgeId}>
              {edge.displayName} ({edge.edgeId})
            </option>
          ))}
        </ConsoleSelect>
        {simulationHint ? (
          <p className="text-[11px] text-amber-200/90">{simulationHint}</p>
        ) : null}
      </ConsoleCard>

      {isAdmin ? (
        <ConsoleCard padding="sm" className="grid gap-2 md:grid-cols-[1fr_auto] md:items-end">
          <div className="grid gap-1.5">
            <Label htmlFor="grant-edge">Engineer edge grant</Label>
            <div className="flex flex-wrap gap-2">
              <ConsoleSelect
                id="grant-edge"
                aria-label="Edge for grant"
                value={grantEdgeId || selected?.edgeId || ''}
                onChange={(event) => setGrantEdgeId(event.target.value)}
              >
                {edges.map((edge) => (
                  <option key={edge.edgeId} value={edge.edgeId}>{edge.displayName}</option>
                ))}
              </ConsoleSelect>
              <Input
                aria-label="Engineer user id"
                value={grantUserId}
                onChange={(event) => setGrantUserId(event.target.value)}
                placeholder="Engineer subject / user id"
                className="min-w-[14rem] font-mono text-xs"
              />
            </div>
          </div>
          <BtnGhost onClick={() => void handleGrant()} disabled={busy || !grantUserId.trim()} className="text-xs">
            <UserPlus className="size-3.5" />
            Grant write access
          </BtnGhost>
        </ConsoleCard>
      ) : null}

      {panelError ? (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
          {panelError}
        </div>
      ) : null}

      <RegisterDialog
        open={registerOpen}
        onOpenChange={setRegisterOpen}
        edgeId={newEdgeId}
        displayName={newDisplayName}
        onEdgeIdChange={setNewEdgeId}
        onDisplayNameChange={setNewDisplayName}
        onSubmit={() => void handleRegister()}
        busy={busy}
      />

      <Dialog open={Boolean(enrollmentToken)} onOpenChange={(open) => !open && closeEnrollment()}>
        <DialogContent
          aria-label="Enrollment token"
          showCloseButton={false}
          className="instrument-panel instrument-grain border-[#FF7A00]/20 sm:max-w-md"
        >
          <DialogHeader>
            <DialogTitle className="font-heading text-lg">One-time enrollment token</DialogTitle>
            <DialogDescription>
              Copy this token now for IT on the DMZ VM. It is not stored in the browser and cannot be shown again.
            </DialogDescription>
          </DialogHeader>
          <div className="rounded-md border border-border bg-muted/40 p-3 font-mono text-xs break-all">
            {enrollmentToken}
          </div>
          <p className="text-[11px] text-muted-foreground">Edge: {tokenEdgeId}</p>
          <DialogFooter>
            <Button
              onClick={async () => {
                if (enrollmentToken) await navigator.clipboard.writeText(enrollmentToken);
              }}
            >
              Copy token
            </Button>
            <Button variant="outline" onClick={closeEnrollment}>Close</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

type RegisterDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  edgeId: string;
  displayName: string;
  onEdgeIdChange: (value: string) => void;
  onDisplayNameChange: (value: string) => void;
  onSubmit: () => void;
  busy: boolean;
};

function RegisterDialog({
  open,
  onOpenChange,
  edgeId,
  displayName,
  onEdgeIdChange,
  onDisplayNameChange,
  onSubmit,
  busy,
}: RegisterDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent aria-label="Register edge" showCloseButton={false} className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="font-heading text-lg">Register edge device</DialogTitle>
          <DialogDescription>
            Creates the cloud record before IT enrolls HiveMQ Edge on the DMZ VM.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <div className="grid gap-1.5">
            <Label htmlFor="edge-id">Edge ID</Label>
            <Input id="edge-id" value={edgeId} onChange={(e) => onEdgeIdChange(e.target.value)} className="font-mono text-xs" />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="edge-name">Display name</Label>
            <Input id="edge-name" value={displayName} onChange={(e) => onDisplayNameChange(e.target.value)} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={onSubmit} disabled={busy || !edgeId.trim()}>Register</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

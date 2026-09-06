import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Plus, Trash2, Zap, FolderTree } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { unsGraphQLClient } from '../../services/graphql/client';
import type {
  GraphqlConnectivityProtocol,
  GraphqlConnectivityServer,
  GraphqlConnectivityServerInput,
} from '../../services/graphql/types';
import { AccessRestricted } from '../common/AccessRestricted';
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
import {
  BtnGhost,
  BtnPrimary,
  ConsoleCard,
  ConsoleSelect,
  FilterToolbar,
  PageContent,
  PageShell,
} from '../ui/console-ui';
import {
  PROTOCOL_TABS,
  type ConnectivityTabId,
  filterServers,
  formatLastTestedAt,
  isProtocolInSlice,
  statusDotClass,
  statusLabel,
} from '../../lib/connectivity/map-servers';
import {
  AUTH_MODE_TO_GQL,
  CONNECTIVITY_SECURITY_MODES,
  CONNECTIVITY_SECURITY_POLICIES,
  SECURITY_MODE_TO_GQL,
  SECURITY_POLICY_TO_GQL,
  validateConnectivityServer,
  type ConnectivityAuthMode,
  type ConnectivitySecurityMode,
  type ConnectivitySecurityPolicy,
} from '../../lib/connectivity/validate-server';
import { BrowseDataDrawer } from './BrowseDataDrawer';
import { SignalsTab } from './SignalsTab';

function newServerId(): string {
  return `srv_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

export const ConnectivityView: React.FC = () => {
  const { hasPermission } = useAuth();
  const canMutate = hasPermission('connectivity');

  const [pageTab, setPageTab] = useState<'servers' | 'signals'>('servers');
  const [search, setSearch] = useState('');
  const [servers, setServers] = useState<GraphqlConnectivityServer[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [draftProtocol, setDraftProtocol] = useState<ConnectivityTabId>('opc_ua');
  const [draftName, setDraftName] = useState('');
  const [draftEndpoint, setDraftEndpoint] = useState('opc.tcp://');
  const [draftAuthMode, setDraftAuthMode] = useState<ConnectivityAuthMode>('anonymous');
  const [draftSecurityPolicy, setDraftSecurityPolicy] =
    useState<ConnectivitySecurityPolicy>('None');
  const [draftSecurityMode, setDraftSecurityMode] = useState<ConnectivitySecurityMode>('None');
  const [draftUsername, setDraftUsername] = useState('');
  const [draftPassword, setDraftPassword] = useState('');
  const [draftCertificate, setDraftCertificate] = useState('');
  const [draftPrivateKey, setDraftPrivateKey] = useState('');
  const [draftServerCertificate, setDraftServerCertificate] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [browseServer, setBrowseServer] = useState<GraphqlConnectivityServer | null>(null);

  const loadServers = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      setServers(await unsGraphQLClient.getConnectivityServers('OPC_UA'));
    } catch (err) {
      setLoadError(
        err instanceof Error
          ? `Connectivity catalog could not be loaded. ${err.message}`
          : 'Connectivity catalog could not be loaded. GraphQL returned an error — not an empty plant.',
      );
      setServers([]);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    if (!canMutate) return;
    void loadServers();
  }, [canMutate, loadServers]);

  const filtered = useMemo(() => filterServers(servers, search), [servers, search]);

  const resetDraft = () => {
    setDraftProtocol('opc_ua');
    setDraftName('');
    setDraftEndpoint('opc.tcp://');
    setDraftAuthMode('anonymous');
    setDraftSecurityPolicy('None');
    setDraftSecurityMode('None');
    setDraftUsername('');
    setDraftPassword('');
    setDraftCertificate('');
    setDraftPrivateKey('');
    setDraftServerCertificate('');
    setSaveError(null);
  };

  const handleAdd = async () => {
    const invalid = validateConnectivityServer({
      protocol: draftProtocol,
      name: draftName,
      endpoint: draftEndpoint,
      authMode: draftAuthMode,
      securityPolicy: draftSecurityPolicy,
      securityMode: draftSecurityMode,
      username: draftUsername,
      password: draftPassword,
      certificate: draftCertificate,
      privateKey: draftPrivateKey,
      serverCertificate: draftServerCertificate,
    });
    if (invalid) {
      setSaveError(invalid);
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      const input: GraphqlConnectivityServerInput = {
        id: newServerId(),
        name: draftName.trim(),
        protocol: 'OPC_UA' as GraphqlConnectivityProtocol,
        endpoint: draftEndpoint.trim(),
        authMode: AUTH_MODE_TO_GQL[draftAuthMode],
        securityPolicy: SECURITY_POLICY_TO_GQL[draftSecurityPolicy],
        securityMode: SECURITY_MODE_TO_GQL[draftSecurityMode],
        username: draftUsername.trim(),
        password: draftPassword,
        certificate: draftCertificate.trim(),
        privateKey: draftPrivateKey.trim(),
        serverCertificate: draftServerCertificate.trim(),
      };
      const saved = await unsGraphQLClient.saveConnectivityServer(input);
      setServers((prev) => [...prev, saved]);
      setAddOpen(false);
      resetDraft();
      await applyConnectionTest(saved);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Server was not added');
    } finally {
      setSaving(false);
    }
  };

  const applyConnectionTest = async (server: GraphqlConnectivityServer) => {
    setTestingId(server.id);
    try {
      const result = await unsGraphQLClient.testOpcUaConnection(server.endpoint);
      setServers((prev) =>
        prev.map((s) =>
          s.id === server.id
            ? {
                ...s,
                lastStatus: result.ok ? 'connected' : 'failed',
                lastError: result.error ?? '',
                lastTestedAt: new Date().toISOString(),
              }
            : s,
        ),
      );
    } catch {
      setServers((prev) =>
        prev.map((s) =>
          s.id === server.id
            ? { ...s, lastStatus: 'failed', lastError: 'Test failed', lastTestedAt: new Date().toISOString() }
            : s,
        ),
      );
    } finally {
      setTestingId(null);
    }
  };

  const handleTest = async (server: GraphqlConnectivityServer) => {
    await applyConnectionTest(server);
  };

  const handleDelete = async (server: GraphqlConnectivityServer) => {
    setDeletingId(server.id);
    setConfirmDeleteId(null);
    try {
      await unsGraphQLClient.deleteConnectivityServer(server.id);
      setServers((prev) => prev.filter((s) => s.id !== server.id));
      setBrowseServer((prev) => (prev?.id === server.id ? null : prev));
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : 'Delete failed');
    } finally {
      setDeletingId(null);
    }
  };

  const openSignalTerminal = (server: GraphqlConnectivityServer) => {
    setBrowseServer(server);
  };

  const applyServerUpdate = (updated: GraphqlConnectivityServer) => {
    setServers((prev) => prev.map((s) => (s.id === updated.id ? { ...s, ...updated } : s)));
    setBrowseServer((prev) => (prev && prev.id === updated.id ? { ...prev, ...updated } : prev));
  };

  if (!canMutate) {
    return (
      <PageShell id="connectivity-view" scroll={false} className="flex flex-col font-mono">
        <AccessRestricted featureKey="connectivity" />
      </PageShell>
    );
  }

  return (
    <PageShell id="connectivity-view" scroll={false} className="flex flex-col font-mono">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <PageContent fullWidth className="flex min-h-full flex-col gap-3 pb-4">
          <FilterToolbar
            tabs={{
              items: [
                { id: 'servers', label: 'Servers' },
                { id: 'signals', label: 'Signals' },
              ],
              active: pageTab,
              onChange: (id) => setPageTab(id as 'servers' | 'signals'),
            }}
            search={
              pageTab === 'servers'
                ? { value: search, onChange: setSearch, placeholder: 'Search name or endpoint…' }
                : undefined
            }
            trailing={
              pageTab === 'servers' && canMutate ? (
                <BtnPrimary
                  onClick={() => {
                    resetDraft();
                    setAddOpen(true);
                  }}
                  className="px-3 py-1.5 text-xs"
                  aria-label="Add Server"
                >
                  <Plus className="size-3.5" />
                  Add Server
                </BtnPrimary>
              ) : null
            }
          />

          {pageTab === 'signals' ? (
            <SignalsTab />
          ) : (
            <>
              {loadError && (
                <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
                  {loadError}
                </div>
              )}

              {loading ? (
                <ConsoleCard padding="md" className="text-sm text-muted-foreground">
                  Loading OPC UA servers…
                </ConsoleCard>
              ) : loadError ? null : filtered.length === 0 ? (
                <ConsoleCard padding="md" className="text-sm text-muted-foreground">
                  {search
                    ? 'No servers match this search.'
                    : 'No OPC UA servers yet. Add one to test, browse, and subscribe its variables.'}
                </ConsoleCard>
              ) : (
                <ConsoleCard padding="none" className="overflow-hidden">
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[860px] border-collapse text-left text-sm">
                      <thead className="border-b border-border bg-muted/50 text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
                        <tr>
                          <th className="px-4 py-3">Name</th>
                          <th className="px-4 py-3">Endpoint</th>
                          <th className="px-4 py-3">Status</th>
                          <th className="px-4 py-3">Last test</th>
                          <th className="px-4 py-3 text-right">Actions</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border text-xs">
                        {filtered.map((server) => (
                          <tr
                            key={server.id}
                            className="cursor-pointer hover:bg-muted/60"
                            onClick={() => openSignalTerminal(server)}
                          >
                            <td className="px-4 py-3">
                              <button
                                type="button"
                                aria-label={`Open ${server.name}`}
                                onClick={() => openSignalTerminal(server)}
                                className="font-heading text-left font-semibold text-foreground hover:text-[#FF7A00] hover:underline"
                              >
                                {server.name}
                              </button>
                            </td>
                            <td className="px-4 py-3 font-mono text-[11px] text-muted-foreground">
                              {server.endpoint}
                            </td>
                            <td className="px-4 py-3">
                              <div className="flex items-center gap-2">
                                <span className={`size-2 rounded-full ${statusDotClass(server.lastStatus)}`} />
                                <span className="text-foreground">{statusLabel(server.lastStatus)}</span>
                                {server.lastError && (
                                  <span className="truncate text-[10px] text-rose-400" title={server.lastError}>
                                    {server.lastError}
                                  </span>
                                )}
                              </div>
                            </td>
                            <td className="px-4 py-3 font-mono text-[11px] tabular-nums text-muted-foreground">
                              {formatLastTestedAt(server.lastTestedAt)}
                            </td>
                            <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                              <div className="flex items-center justify-end gap-1">
                                <BtnGhost
                                  onClick={() => void handleTest(server)}
                                  disabled={testingId === server.id}
                                  className="px-2 py-1 text-[11px]"
                                  aria-label="Test"
                                >
                                  <Zap className="size-3.5" />
                                  Test
                                </BtnGhost>
                                <BtnGhost
                                  onClick={() => openSignalTerminal(server)}
                                  className="px-2 py-1 text-[11px]"
                                  aria-label="Browse data"
                                >
                                  <FolderTree className="size-3.5" />
                                  Browse data
                                </BtnGhost>
                                <BtnGhost
                                  onClick={() => setConfirmDeleteId(server.id)}
                                  disabled={deletingId === server.id}
                                  className="px-2 py-1 text-[11px] text-rose-400 hover:text-rose-300"
                                  aria-label="Delete"
                                >
                                  <Trash2 className="size-3.5" />
                                  Delete
                                </BtnGhost>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </ConsoleCard>
              )}
            </>
          )}
        </PageContent>
      </div>

      <Dialog
        open={addOpen}
        onOpenChange={(open) => {
          setAddOpen(open);
          if (!open) resetDraft();
        }}
      >
        <DialogContent
          aria-label="Add OPC UA server"
          showCloseButton={false}
          className="instrument-panel instrument-grain !overflow-y-auto max-h-[min(90dvh,52rem)] gap-4 overflow-x-hidden border-[#FF7A00]/20 sm:max-w-lg"
        >
          <DialogHeader>
            <p className="text-[10px] font-medium uppercase tracking-[0.22em] text-[#FF7A00]">
              New connection
            </p>
            <DialogTitle className="font-heading text-lg">Add OPC UA server</DialogTitle>
            <DialogDescription>
              OPC UA is what this slice serves. Other protocols stay listed for later.
            </DialogDescription>
          </DialogHeader>
          {saveError && (
            <div className="rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              {saveError}
            </div>
          )}
          <div className="grid gap-3">
            <div className="grid gap-1.5">
              <Label htmlFor="conn-protocol">Protocol</Label>
              <ConsoleSelect
                id="conn-protocol"
                aria-label="Protocol"
                value={draftProtocol}
                onChange={(e) => setDraftProtocol(e.target.value as ConnectivityTabId)}
              >
                {PROTOCOL_TABS.map((tab) => (
                  <option key={tab.id} value={tab.id} disabled={!isProtocolInSlice(tab.id)}>
                    {tab.label}
                    {isProtocolInSlice(tab.id) ? '' : ' — later'}
                  </option>
                ))}
              </ConsoleSelect>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="conn-name">Name</Label>
              <Input
                id="conn-name"
                aria-label="Name"
                value={draftName}
                onChange={(e) => setDraftName(e.target.value)}
                placeholder="opcplc"
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="conn-endpoint">Endpoint</Label>
              <Input
                id="conn-endpoint"
                aria-label="Endpoint"
                value={draftEndpoint}
                onChange={(e) => setDraftEndpoint(e.target.value)}
                placeholder="opc.tcp://host.docker.internal:50000/"
                className="font-mono text-xs"
              />
            </div>
          </div>

          <fieldset className="space-y-2 rounded-md border border-border p-3">
            <legend className="px-1 text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
              Security
            </legend>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="grid gap-1.5">
                <Label htmlFor="conn-sec-policy">Security policy</Label>
                <ConsoleSelect
                  id="conn-sec-policy"
                  aria-label="Security policy"
                  value={draftSecurityPolicy}
                  onChange={(e) => {
                    const next = e.target.value as ConnectivitySecurityPolicy;
                    setDraftSecurityPolicy(next);
                    setDraftSecurityMode(next === 'None' ? 'None' : 'SignAndEncrypt');
                  }}
                >
                  {CONNECTIVITY_SECURITY_POLICIES.map((policy) => (
                    <option key={policy} value={policy}>
                      {policy}
                    </option>
                  ))}
                </ConsoleSelect>
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="conn-sec-mode">Security mode</Label>
                <ConsoleSelect
                  id="conn-sec-mode"
                  aria-label="Security mode"
                  value={draftSecurityMode}
                  disabled={draftSecurityPolicy === 'None'}
                  onChange={(e) => setDraftSecurityMode(e.target.value as ConnectivitySecurityMode)}
                >
                  {CONNECTIVITY_SECURITY_MODES.filter(
                    (mode) => draftSecurityPolicy !== 'None' || mode === 'None',
                  ).map((mode) => (
                    <option key={mode} value={mode}>
                      {mode}
                    </option>
                  ))}
                </ConsoleSelect>
              </div>
            </div>
            {(draftSecurityPolicy !== 'None' || draftAuthMode === 'x509') && (
              <>
                <p className="text-[11px] text-muted-foreground">
                  Client certificate for the secure channel — not part of Anonymous login.
                </p>
                <div className="grid gap-1.5">
                  <Label htmlFor="conn-cert">Certificate path</Label>
                  <Input
                    id="conn-cert"
                    aria-label="Certificate path"
                    value={draftCertificate}
                    onChange={(e) => setDraftCertificate(e.target.value)}
                    placeholder="/certs/client.der"
                    className="font-mono text-xs"
                  />
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="conn-key">Private key path</Label>
                  <Input
                    id="conn-key"
                    aria-label="Private key path"
                    value={draftPrivateKey}
                    onChange={(e) => setDraftPrivateKey(e.target.value)}
                    placeholder="/certs/client.key"
                    className="font-mono text-xs"
                  />
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="conn-server-cert">Server certificate path</Label>
                  <Input
                    id="conn-server-cert"
                    aria-label="Server certificate path"
                    value={draftServerCertificate}
                    onChange={(e) => setDraftServerCertificate(e.target.value)}
                    placeholder="optional"
                    className="font-mono text-xs"
                  />
                </div>
              </>
            )}
          </fieldset>

          <fieldset className="space-y-2 rounded-md border border-border p-3">
            <legend className="px-1 text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
              Authentication
            </legend>
            <div className="flex flex-wrap gap-3 text-xs text-foreground">
              {(
                [
                  ['anonymous', 'Anonymous'],
                  ['username', 'Username/Password'],
                  ['x509', 'X509 Certificate'],
                ] as const
              ).map(([value, label]) => (
                <label key={value} className="inline-flex items-center gap-2">
                  <input
                    type="radio"
                    name="connectivity-auth-mode"
                    value={value}
                    checked={draftAuthMode === value}
                    onChange={() => setDraftAuthMode(value)}
                  />
                  {label}
                </label>
              ))}
            </div>
            {draftAuthMode === 'username' && (
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="grid gap-1.5">
                  <Label htmlFor="conn-user">Username</Label>
                  <Input
                    id="conn-user"
                    aria-label="Username"
                    value={draftUsername}
                    onChange={(e) => setDraftUsername(e.target.value)}
                    autoComplete="off"
                  />
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="conn-pass">Password</Label>
                  <Input
                    id="conn-pass"
                    aria-label="Password"
                    type="password"
                    value={draftPassword}
                    onChange={(e) => setDraftPassword(e.target.value)}
                    autoComplete="new-password"
                  />
                </div>
              </div>
            )}
          </fieldset>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setAddOpen(false);
                resetDraft();
              }}
            >
              Cancel
            </Button>
            <Button onClick={() => void handleAdd()} disabled={saving} aria-label="Add">
              {saving ? 'Adding…' : 'Add'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(confirmDeleteId)} onOpenChange={(open) => !open && setConfirmDeleteId(null)}>
        <DialogContent
          aria-label="Confirm delete"
          showCloseButton={false}
          className="instrument-panel instrument-grain border-[#FF7A00]/20 sm:max-w-sm"
        >
          <DialogHeader>
            <DialogTitle className="font-heading text-lg">Delete this server?</DialogTitle>
            <DialogDescription>
              The server and its subscribed tags are removed from the catalog. The OPC UA
              collector stops publishing those topics on its next reload.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmDeleteId(null)}>
              Cancel
            </Button>
            <Button
              onClick={() => {
                const target = servers.find((s) => s.id === confirmDeleteId);
                if (target) void handleDelete(target);
              }}
              disabled={deletingId === confirmDeleteId}
              aria-label="Confirm"
            >
              {deletingId === confirmDeleteId ? 'Deleting…' : 'Confirm'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {browseServer && (
        <BrowseDataDrawer
          server={browseServer}
          onClose={() => setBrowseServer(null)}
          onSubscribed={applyServerUpdate}
        />
      )}
    </PageShell>
  );
};

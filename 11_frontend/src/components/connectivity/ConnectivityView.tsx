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
import {
  BtnGhost,
  BtnPrimary,
  BtnSecondary,
  ConsoleCard,
  ConsoleInput,
  ConsoleSelect,
  FilterToolbar,
  PageContent,
  PageShell,
  consoleTokens,
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
  CONNECTIVITY_SECURITY_MODES,
  CONNECTIVITY_SECURITY_POLICIES,
  validateConnectivityServer,
  type ConnectivityAuthMode,
  type ConnectivitySecurityMode,
  type ConnectivitySecurityPolicy,
} from '../../lib/connectivity/validate-server';
import { BrowseDataDrawer } from './BrowseDataDrawer';

function newServerId(): string {
  return `srv_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

export const ConnectivityView: React.FC = () => {
  const { hasPermission } = useAuth();
  const canMutate = hasPermission('connectivity');

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
    const result = await unsGraphQLClient.getConnectivityServers('OPC_UA');
    if (result === null) {
      setLoadError('Connectivity catalog could not be loaded. GraphQL is unreachable.');
      setServers([]);
    } else {
      setServers(result);
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
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : 'Delete failed');
    } finally {
      setDeletingId(null);
    }
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
            search={{ value: search, onChange: setSearch, placeholder: 'Search name or endpoint…' }}
            trailing={
              canMutate ? (
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

          {loadError && (
            <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              {loadError}
            </div>
          )}

          {loading ? (
            <ConsoleCard padding="md" className="text-sm text-zinc-500">
              Loading OPC UA servers…
            </ConsoleCard>
          ) : filtered.length === 0 ? (
            <ConsoleCard padding="md" className="text-sm text-zinc-500">
              {search
                ? 'No servers match this search.'
                : 'No OPC UA servers yet. Add one to test, browse, and subscribe its variables.'}
            </ConsoleCard>
          ) : (
            <ConsoleCard padding="none" className="overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[860px] border-collapse text-left text-sm">
                  <thead className="border-b border-zinc-800 bg-zinc-900/80 text-[11px] uppercase text-zinc-500">
                    <tr>
                      <th className="px-4 py-3 font-medium">Name</th>
                      <th className="px-4 py-3 font-medium">Endpoint</th>
                      <th className="px-4 py-3 font-medium">Status</th>
                      <th className="px-4 py-3 font-medium">Last test</th>
                      <th className="px-4 py-3 text-right font-medium">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-800/80 text-xs">
                    {filtered.map((server) => (
                      <tr key={server.id} className="hover:bg-zinc-800/30">
                        <td className="px-4 py-3 font-semibold text-white">{server.name}</td>
                        <td className="px-4 py-3 font-mono text-[11px] text-zinc-400">
                          {server.endpoint}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <span className={`size-2 rounded-full ${statusDotClass(server.lastStatus)}`} />
                            <span className="text-zinc-300">{statusLabel(server.lastStatus)}</span>
                            {server.lastError && (
                              <span className="truncate text-[10px] text-rose-400" title={server.lastError}>
                                {server.lastError}
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="px-4 py-3 text-zinc-500">
                          {formatLastTestedAt(server.lastTestedAt)}
                        </td>
                        <td className="px-4 py-3">
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
                              onClick={() => setBrowseServer(server)}
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
        </PageContent>
      </div>

      {addOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-3 backdrop-blur-sm">
          <div
            className={`${consoleTokens.card} flex max-h-[90vh] w-full max-w-lg flex-col gap-3 overflow-y-auto p-5 shadow-2xl`}
            role="dialog"
            aria-label="Add OPC UA server"
          >
            <h2 className="text-sm font-semibold text-white">Add OPC UA server</h2>
            <p className="text-[11px] text-zinc-500">
              OPC UA is what this slice serves. Other protocols stay listed for later.
            </p>
            {saveError && (
              <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
                {saveError}
              </div>
            )}
            <label className="block space-y-1.5">
              <span className="text-xs font-medium text-zinc-500">Protocol</span>
              <ConsoleSelect
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
            </label>
            <label className="block space-y-1.5">
              <span className="text-xs font-medium text-zinc-500">Name</span>
              <ConsoleInput
                aria-label="Name"
                value={draftName}
                onChange={(e) => setDraftName(e.target.value)}
                placeholder="opcplc"
              />
            </label>
            <label className="block space-y-1.5">
              <span className="text-xs font-medium text-zinc-500">Endpoint</span>
              <ConsoleInput
                aria-label="Endpoint"
                value={draftEndpoint}
                onChange={(e) => setDraftEndpoint(e.target.value)}
                placeholder="opc.tcp://host.docker.internal:50000/"
                className="font-mono text-xs"
              />
            </label>

            <fieldset className="space-y-2 rounded-xl border border-zinc-800 p-3">
              <legend className="px-1 text-[10px] font-medium uppercase tracking-wider text-zinc-500">
                Security
              </legend>
              <label className="block space-y-1.5">
                <span className="text-xs font-medium text-zinc-500">Security policy</span>
                <ConsoleSelect
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
              </label>
              <label className="block space-y-1.5">
                <span className="text-xs font-medium text-zinc-500">Security mode</span>
                <ConsoleSelect
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
              </label>
              {(draftSecurityPolicy !== 'None' || draftAuthMode === 'x509') && (
                <>
                  <p className="text-[11px] text-zinc-500">
                    Client certificate for the secure channel — not part of Anonymous login.
                  </p>
                  <label className="block space-y-1.5">
                    <span className="text-xs font-medium text-zinc-500">Certificate path</span>
                    <ConsoleInput
                      aria-label="Certificate path"
                      value={draftCertificate}
                      onChange={(e) => setDraftCertificate(e.target.value)}
                      placeholder="/certs/client.der"
                      className="font-mono text-xs"
                    />
                  </label>
                  <label className="block space-y-1.5">
                    <span className="text-xs font-medium text-zinc-500">Private key path</span>
                    <ConsoleInput
                      aria-label="Private key path"
                      value={draftPrivateKey}
                      onChange={(e) => setDraftPrivateKey(e.target.value)}
                      placeholder="/certs/client.key"
                      className="font-mono text-xs"
                    />
                  </label>
                  <label className="block space-y-1.5">
                    <span className="text-xs font-medium text-zinc-500">Server certificate path</span>
                    <ConsoleInput
                      aria-label="Server certificate path"
                      value={draftServerCertificate}
                      onChange={(e) => setDraftServerCertificate(e.target.value)}
                      placeholder="optional"
                      className="font-mono text-xs"
                    />
                  </label>
                </>
              )}
            </fieldset>

            <fieldset className="space-y-2 rounded-xl border border-zinc-800 p-3">
              <legend className="px-1 text-[10px] font-medium uppercase tracking-wider text-zinc-500">
                Authentication
              </legend>
              <div className="flex flex-wrap gap-3 text-xs text-zinc-300">
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
                <>
                  <label className="block space-y-1.5">
                    <span className="text-xs font-medium text-zinc-500">Username</span>
                    <ConsoleInput
                      aria-label="Username"
                      value={draftUsername}
                      onChange={(e) => setDraftUsername(e.target.value)}
                      autoComplete="off"
                    />
                  </label>
                  <label className="block space-y-1.5">
                    <span className="text-xs font-medium text-zinc-500">Password</span>
                    <ConsoleInput
                      aria-label="Password"
                      type="password"
                      value={draftPassword}
                      onChange={(e) => setDraftPassword(e.target.value)}
                      autoComplete="new-password"
                    />
                  </label>
                </>
              )}
            </fieldset>

            <div className="flex items-center justify-end gap-2 pt-1">
              <BtnSecondary
                onClick={() => {
                  setAddOpen(false);
                  resetDraft();
                }}
                className="px-3 py-1.5 text-xs"
              >
                Cancel
              </BtnSecondary>
              <BtnPrimary
                onClick={() => void handleAdd()}
                disabled={saving}
                className="px-4 py-1.5 text-xs"
                aria-label="Add"
              >
                {saving ? 'Adding…' : 'Add'}
              </BtnPrimary>
            </div>
          </div>
        </div>
      )}

      {confirmDeleteId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-3 backdrop-blur-sm">
          <div
            className={`${consoleTokens.card} flex w-full max-w-sm flex-col gap-3 p-5 shadow-2xl`}
            role="dialog"
            aria-label="Confirm delete"
          >
            <h2 className="text-sm font-semibold text-white">Delete this server?</h2>
            <p className="text-xs text-zinc-500">
              The server and its subscribed tags are removed from the catalog. The OPC UA
              collector stops publishing those topics on its next reload.
            </p>
            <div className="flex items-center justify-end gap-2 pt-1">
              <BtnSecondary
                onClick={() => setConfirmDeleteId(null)}
                className="px-3 py-1.5 text-xs"
              >
                Cancel
              </BtnSecondary>
              <BtnPrimary
                onClick={() => {
                  const target = servers.find((s) => s.id === confirmDeleteId);
                  if (target) void handleDelete(target);
                }}
                disabled={deletingId === confirmDeleteId}
                className="px-4 py-1.5 text-xs"
                aria-label="Confirm"
              >
                {deletingId === confirmDeleteId ? 'Deleting…' : 'Confirm'}
              </BtnPrimary>
            </div>
          </div>
        </div>
      )}

      {browseServer && (
        <BrowseDataDrawer
          server={browseServer}
          onClose={() => setBrowseServer(null)}
          onSubscribed={(updated) => {
            setServers((prev) => prev.map((s) => (s.id === updated.id ? updated : s)));
          }}
        />
      )}
    </PageShell>
  );
};

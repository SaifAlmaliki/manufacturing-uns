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
import { BrowseDataDrawer } from './BrowseDataDrawer';

function newServerId(): string {
  return `srv_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

export const ConnectivityView: React.FC = () => {
  const { hasPermission } = useAuth();
  const canMutate = hasPermission('connectivity');

  const [activeTab, setActiveTab] = useState<ConnectivityTabId>('opc_ua');
  const [search, setSearch] = useState('');
  const [servers, setServers] = useState<GraphqlConnectivityServer[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [draftName, setDraftName] = useState('');
  const [draftEndpoint, setDraftEndpoint] = useState('opc.tcp://');
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

  const handleAdd = async () => {
    if (!draftName.trim() || !draftEndpoint.trim()) {
      setSaveError('Name and endpoint are required.');
      return;
    }
    setSaving(true);
    setSaveError(null);
    const input: GraphqlConnectivityServerInput = {
      id: newServerId(),
      name: draftName.trim(),
      protocol: 'OPC_UA' as GraphqlConnectivityProtocol,
      endpoint: draftEndpoint.trim(),
    };
    try {
      const saved = await unsGraphQLClient.saveConnectivityServer(input);
      setServers((prev) => [...prev, saved]);
      setAddOpen(false);
      setDraftName('');
      setDraftEndpoint('opc.tcp://');
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Server was not saved');
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async (server: GraphqlConnectivityServer) => {
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

  const showTable = isProtocolInSlice(activeTab);

  return (
    <PageShell id="connectivity-view" scroll={false} className="flex flex-col font-mono">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <PageContent fullWidth className="flex min-h-full flex-col gap-3 pb-4">
          <FilterToolbar
            tabs={{
              items: PROTOCOL_TABS,
              active: activeTab,
              onChange: (id) => setActiveTab(id as ConnectivityTabId),
            }}
            search={{ value: search, onChange: setSearch, placeholder: 'Search name or endpoint…' }}
            trailing={
              canMutate ? (
                <BtnPrimary
                  onClick={() => setAddOpen(true)}
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

          {!showTable ? (
            <ConsoleCard padding="md" className="text-sm text-zinc-500">
              Not in this slice. OPC UA is the only connectivity protocol wired through the
              console catalog in this release.
            </ConsoleCard>
          ) : loading ? (
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
            className={`${consoleTokens.card} flex w-full max-w-md flex-col gap-3 p-5 shadow-2xl`}
            role="dialog"
            aria-label="Add OPC UA server"
          >
            <h2 className="text-sm font-semibold text-white">Add OPC UA server</h2>
            {saveError && (
              <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
                {saveError}
              </div>
            )}
            <label className="block space-y-1.5">
              <span className="text-xs font-medium text-zinc-500">Name</span>
              <ConsoleInput
                value={draftName}
                onChange={(e) => setDraftName(e.target.value)}
                placeholder="opcplc"
              />
            </label>
            <label className="block space-y-1.5">
              <span className="text-xs font-medium text-zinc-500">Endpoint</span>
              <ConsoleInput
                value={draftEndpoint}
                onChange={(e) => setDraftEndpoint(e.target.value)}
                placeholder="opc.tcp://desktop-h4hdql2:50000/"
                className="font-mono text-xs"
              />
            </label>
            <div className="flex items-center justify-end gap-2 pt-1">
              <BtnSecondary onClick={() => setAddOpen(false)} className="px-3 py-1.5 text-xs">
                Cancel
              </BtnSecondary>
              <BtnPrimary
                onClick={() => void handleAdd()}
                disabled={saving}
                className="px-4 py-1.5 text-xs"
              >
                {saving ? 'Saving…' : 'Save'}
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

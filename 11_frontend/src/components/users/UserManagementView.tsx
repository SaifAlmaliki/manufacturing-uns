import React, { useEffect, useMemo, useState } from 'react';
import { ExternalLink, Layers, Shield, Users } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { fetchRealmMembers, type DirectoryResult, type RealmMember } from '../../lib/auth/directory';
import { platformConfig } from '../../lib/platform/config';
import { unsGraphQLClient } from '../../services/graphql/client';
import type { AccessAssetDto, AccessGroupDto } from '../../services/graphql/types';
import {
  UserRole,
  SYSTEM_FEATURES,
  ROLE_CONFIGS,
} from '../../types/rbac';
import { AccessRestricted } from '../common/AccessRestricted';
import {
  BtnGhost,
  BtnPrimary,
  BtnSecondary,
  PageShell,
  PageContent,
  ConsoleCard,
  ConsoleInput,
  SegmentTabs,
  FilterToolbar,
} from '../ui/console-ui';

type SubTab = 'directory' | 'groups' | 'roles';

type GroupEditor = {
  id: number | null;
  name: string;
  selectedPaths: string[];
  memberIds: string[];
};

type AssignPanel = {
  memberId: string;
  selectedGroupIds: number[];
};

function openKeycloak() {
  window.open(
    `${platformConfig.authBaseUrl}/admin/${platformConfig.authRealm}/console/`,
    '_blank',
    'noopener',
  );
}

function segmentDepth(path: string): number {
  return Math.max(0, path.split('/').filter(Boolean).length - 1);
}

function isCoveredByAncestor(path: string, selectedPaths: string[]): boolean {
  return selectedPaths.some((root) => path !== root && path.startsWith(`${root}/`));
}

function toggleSelectedPath(selectedPaths: string[], path: string): string[] {
  if (selectedPaths.includes(path)) {
    return selectedPaths.filter((item) => item !== path);
  }
  return [...selectedPaths.filter((item) => item !== path && !item.startsWith(`${path}/`)), path];
}

function groupsForMember(groups: AccessGroupDto[], memberId: string): AccessGroupDto[] {
  return groups.filter((group) => group.subjects.includes(memberId));
}

function OpenKeycloakButton() {
  return (
    <BtnSecondary onClick={openKeycloak}>
      <ExternalLink className="size-3.5" />
      Open Keycloak
    </BtnSecondary>
  );
}

function DirectoryState({ title, body }: { title: string; body: string }) {
  return (
    <ConsoleCard padding="md" className="text-sm text-zinc-400">
      <h3 className="mb-2 font-semibold text-white">{title}</h3>
      <p className="mb-3 whitespace-pre-line leading-relaxed">{body}</p>
      <OpenKeycloakButton />
    </ConsoleCard>
  );
}

function GroupChip({ name }: { name: string }) {
  return (
    <span className="rounded-md border border-[#FF7A00]/30 bg-[#FF7A00]/10 px-2 py-0.5 text-[9px] font-bold text-[#FF7A00]">
      {name}
    </span>
  );
}

function AssetPicker({
  assets,
  selectedPaths,
  onToggle,
}: {
  assets: AccessAssetDto[];
  selectedPaths: string[];
  onToggle: (path: string) => void;
}) {
  const sorted = useMemo(
    () => [...assets].sort((a, b) => a.path.localeCompare(b.path)),
    [assets],
  );

  if (sorted.length === 0) {
    return <p className="text-xs text-zinc-500">No Assets in the model yet.</p>;
  }

  return (
    <div className="max-h-64 space-y-0.5 overflow-y-auto rounded-xl border border-zinc-800 bg-zinc-950/50 p-2">
      {sorted.map((asset) => {
        const included = isCoveredByAncestor(asset.path, selectedPaths);
        const checked = included || selectedPaths.includes(asset.path);
        return (
          <label
            key={asset.path}
            className={`flex items-center gap-2 rounded-lg px-2 py-1 text-xs ${
              included ? 'text-zinc-500' : 'text-zinc-200'
            }`}
            style={{ paddingLeft: segmentDepth(asset.path) * 12 }}
          >
            <input
              type="checkbox"
              checked={checked}
              disabled={included}
              onChange={() => onToggle(asset.path)}
              aria-label={asset.path}
            />
            <span className="font-medium">{asset.segment}</span>
            <span className="font-mono text-[10px] text-zinc-500">{asset.level}</span>
          </label>
        );
      })}
    </div>
  );
}

export const UserManagementView: React.FC = () => {
  const { isAdmin } = useAuth();
  const [activeSubTab, setActiveSubTab] = useState<SubTab>('directory');
  const [result, setResult] = useState<DirectoryResult | null>(null);
  const [groups, setGroups] = useState<AccessGroupDto[]>([]);
  const [assets, setAssets] = useState<AccessAssetDto[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [roleFilter, setRoleFilter] = useState<string>('ALL');
  const [editor, setEditor] = useState<GroupEditor | null>(null);
  const [assignPanel, setAssignPanel] = useState<AssignPanel | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const editorOpen = editor !== null;

  useEffect(() => {
    if (!isAdmin) {
      return;
    }
    let cancelled = false;
    void fetchRealmMembers().then((next) => {
      if (!cancelled) {
        setResult(next);
      }
    });
    void unsGraphQLClient.getAccessGroups().then((next) => {
      if (!cancelled) {
        setGroups(next);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [isAdmin]);

  useEffect(() => {
    if (!editorOpen) {
      return;
    }
    let cancelled = false;
    void unsGraphQLClient.getAssets().then((next) => {
      if (!cancelled) {
        setAssets(next);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [editorOpen]);

  const members = result?.kind === 'members' ? result.members : [];

  const filteredMembers = useMemo(() => {
    return members.filter((member) => {
      const matchSearch =
        member.displayName.toLowerCase().includes(searchQuery.toLowerCase()) ||
        member.username.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (member.email ?? '').toLowerCase().includes(searchQuery.toLowerCase());
      const matchRole =
        roleFilter === 'ALL' ||
        (roleFilter === 'NONE' ? member.roles.length === 0 : member.roles.includes(roleFilter as UserRole));
      return matchSearch && matchRole;
    });
  }, [members, searchQuery, roleFilter]);

  const userTabs = [
    { id: 'directory', label: 'User Directory', icon: Users, badge: members.length || undefined },
    { id: 'groups', label: 'Access Groups', icon: Layers, badge: groups.length || undefined },
    { id: 'roles', label: 'Role Profiles', icon: Shield },
  ];

  const reloadGroups = async () => {
    setGroups(await unsGraphQLClient.getAccessGroups());
  };

  const openCreate = () => {
    setSaveError(null);
    setEditor({ id: null, name: '', selectedPaths: [], memberIds: [] });
  };

  const openEdit = (group: AccessGroupDto) => {
    setSaveError(null);
    setEditor({
      id: group.id,
      name: group.name,
      selectedPaths: group.roots.map((root) => root.path),
      memberIds: [...group.subjects],
    });
  };

  const saveGroup = async () => {
    if (!editor) {
      return;
    }
    const pathToId = new Map<string, number>();
    for (const asset of assets) {
      pathToId.set(asset.path, asset.id);
    }
    for (const group of groups) {
      for (const root of group.roots) {
        pathToId.set(root.path, root.assetId);
      }
    }
    const unresolved = editor.selectedPaths.filter((path) => pathToId.get(path) === undefined);
    if (unresolved.length > 0) {
      setSaveError('Cannot save: a selected Asset has no id');
      return;
    }
    const rootAssetIds = editor.selectedPaths.map((path) => pathToId.get(path) as number);
    try {
      setSaveError(null);
      const saved = await unsGraphQLClient.saveAccessGroup(editor.name, rootAssetIds, editor.id);
      setEditor({ ...editor, id: saved.id });
      await unsGraphQLClient.setAccessGroupMembers(saved.id, editor.memberIds);
      await reloadGroups();
      setEditor(null);
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : String(error));
    }
  };

  const deleteGroup = async (group: AccessGroupDto) => {
    const n = group.subjects.length;
    const people = n === 1 ? 'person' : 'people';
    if (!window.confirm(`Delete ${group.name}? ${n} ${people} will lose that zone.`)) {
      return;
    }
    try {
      setSaveError(null);
      await unsGraphQLClient.deleteAccessGroup(group.id);
      await reloadGroups();
      if (editor?.id === group.id) {
        setEditor(null);
      }
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : String(error));
    }
  };

  const openAssign = (member: RealmMember) => {
    setSaveError(null);
    setAssignPanel({
      memberId: member.id,
      selectedGroupIds: groups.filter((group) => group.subjects.includes(member.id)).map((group) => group.id),
    });
  };

  const saveAssign = async () => {
    if (!assignPanel) {
      return;
    }
    const { memberId, selectedGroupIds } = assignPanel;
    try {
      setSaveError(null);
      await Promise.all(
        groups.map((group) => {
          const selected = selectedGroupIds.includes(group.id);
          const subjects = selected
            ? group.subjects.includes(memberId)
              ? group.subjects
              : [...group.subjects, memberId]
            : group.subjects.filter((subject) => subject !== memberId);
          return unsGraphQLClient.setAccessGroupMembers(group.id, subjects);
        }),
      );
      await reloadGroups();
      setAssignPanel(null);
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : String(error));
      await reloadGroups();
    }
  };

  if (!isAdmin) {
    return (
      <PageShell id="user-management-view" scroll={false} className="flex flex-col font-mono">
        <AccessRestricted featureKey="user_management" />
      </PageShell>
    );
  }

  const assigningMember = assignPanel
    ? members.find((member) => member.id === assignPanel.memberId)
    : undefined;

  const unknownMemberIds = editor
    ? editor.memberIds.filter((id) => !members.some((member) => member.id === id))
    : [];

  return (
    <PageShell id="user-management-view" scroll={false} className="flex flex-col font-mono">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <PageContent fullWidth className="flex min-h-full flex-col gap-3 pb-4">
          <SegmentTabs tabs={userTabs} active={activeSubTab} onChange={(id) => setActiveSubTab(id as SubTab)} />

          {activeSubTab === 'directory' && (
            <>
              {result === null && (
                <DirectoryState
                  title="Reading the realm"
                  body="Asking Keycloak who has access to this plant."
                />
              )}

              {result?.kind === 'forbidden' && (
                <DirectoryState
                  title="This console cannot read the realm's user directory"
                  body="Your account is a console administrator, but the realm did not allow it to list users.
That needs the realm-management view-users role. Users are managed in Keycloak."
                />
              )}

              {result?.kind === 'unreachable' && (
                <DirectoryState
                  title="The realm did not answer"
                  body={`${result.detail} Users are managed in Keycloak.`}
                />
              )}

              {result?.kind === 'members' && (
                <>
                  <FilterToolbar
                    search={{
                      value: searchQuery,
                      onChange: setSearchQuery,
                      placeholder: 'Search name, username, email…',
                    }}
                    selects={[
                      {
                        value: roleFilter,
                        onChange: setRoleFilter,
                        'aria-label': 'Role',
                        options: [
                          { value: 'ALL', label: 'All roles' },
                          { value: 'NONE', label: 'No console role' },
                          { value: 'admin', label: 'Admin' },
                          { value: 'engineer', label: 'Engineer' },
                          { value: 'operator', label: 'Operator' },
                          { value: 'auditor', label: 'Auditor' },
                          { value: 'viewer', label: 'Viewer' },
                        ],
                      },
                    ]}
                    trailing={<OpenKeycloakButton />}
                  />

                  <ConsoleCard padding="none" className="overflow-hidden">
                    <div className="overflow-x-auto">
                      <table className="w-full border-collapse text-left text-xs">
                        <thead>
                          <tr className="border-b border-zinc-800 bg-[#0a0a0b] text-[10px] uppercase tracking-wider text-zinc-500">
                            <th className="px-3 py-2.5">Name</th>
                            <th className="px-3 py-2.5">Username</th>
                            <th className="px-3 py-2.5">Email</th>
                            <th className="px-3 py-2.5">Console roles</th>
                            <th className="px-3 py-2.5">Access groups</th>
                            <th className="px-3 py-2.5">Status</th>
                            <th className="px-3 py-2.5" />
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-zinc-800">
                          {filteredMembers.length === 0 ? (
                            <tr>
                              <td colSpan={7} className="py-10 text-center text-zinc-500">
                                No realm members match this filter.
                              </td>
                            </tr>
                          ) : (
                            filteredMembers.map((member) => {
                              const memberGroups = groupsForMember(groups, member.id);
                              return (
                                <tr key={member.id} className="transition-colors hover:bg-zinc-800/40">
                                  <td className="px-3 py-2.5 font-semibold text-white">{member.displayName}</td>
                                  <td className="px-3 py-2.5 font-mono text-zinc-400">{member.username}</td>
                                  <td className="px-3 py-2.5 text-zinc-500">{member.email ?? '—'}</td>
                                  <td className="px-3 py-2.5">
                                    {member.roles.length === 0 ? (
                                      <span className="text-zinc-500">No console role</span>
                                    ) : (
                                      <div className="flex flex-wrap gap-1">
                                        {member.roles.map((role) => {
                                          const cfg = ROLE_CONFIGS[role];
                                          return (
                                            <span
                                              key={role}
                                              className={`rounded-md border px-2 py-0.5 text-[9px] font-bold ${cfg.badgeBg} ${cfg.badgeText} ${cfg.badgeBorder}`}
                                            >
                                              {cfg.label}
                                            </span>
                                          );
                                        })}
                                      </div>
                                    )}
                                  </td>
                                  <td className="px-3 py-2.5">
                                    {memberGroups.length === 0 ? (
                                      <span className="text-zinc-500">—</span>
                                    ) : (
                                      <div className="flex flex-wrap gap-1">
                                        {memberGroups.map((group) => (
                                          <GroupChip key={group.id} name={group.name} />
                                        ))}
                                      </div>
                                    )}
                                  </td>
                                  <td className="px-3 py-2.5 text-[10px] text-zinc-500">
                                    {member.enabled ? 'Active' : 'Disabled in Keycloak'}
                                  </td>
                                  <td className="px-3 py-2.5 text-right">
                                    <BtnGhost onClick={() => openAssign(member)}>Assign groups</BtnGhost>
                                  </td>
                                </tr>
                              );
                            })
                          )}
                        </tbody>
                      </table>
                    </div>
                  </ConsoleCard>

                  {assignPanel && assigningMember && (
                    <ConsoleCard padding="md" className="space-y-3">
                      <div className="text-sm font-semibold text-white">
                        Assign groups — {assigningMember.displayName}
                      </div>
                      <div className="space-y-1.5">
                        {groups.length === 0 ? (
                          <p className="text-xs text-zinc-500">No Access Groups yet.</p>
                        ) : (
                          groups.map((group) => (
                            <label key={group.id} className="flex items-center gap-2 text-xs text-zinc-200">
                              <input
                                type="checkbox"
                                checked={assignPanel.selectedGroupIds.includes(group.id)}
                                onChange={() => {
                                  setAssignPanel((current) => {
                                    if (!current) {
                                      return current;
                                    }
                                    const selected = current.selectedGroupIds.includes(group.id)
                                      ? current.selectedGroupIds.filter((id) => id !== group.id)
                                      : [...current.selectedGroupIds, group.id];
                                    return { ...current, selectedGroupIds: selected };
                                  });
                                }}
                              />
                              {group.name}
                            </label>
                          ))
                        )}
                      </div>
                      {saveError && <p className="text-xs text-rose-400">{saveError}</p>}
                      <div className="flex flex-wrap gap-2">
                        <BtnPrimary onClick={() => void saveAssign()}>Save</BtnPrimary>
                        <BtnSecondary
                          onClick={() => {
                            setAssignPanel(null);
                            setSaveError(null);
                          }}
                        >
                          Cancel
                        </BtnSecondary>
                      </div>
                    </ConsoleCard>
                  )}
                </>
              )}
            </>
          )}

          {activeSubTab === 'groups' && (
            <>
              <FilterToolbar
                trailing={<BtnPrimary onClick={openCreate}>Create group</BtnPrimary>}
              />

              {saveError && <p className="text-xs text-rose-400">{saveError}</p>}

              {editor ? (
                <ConsoleCard padding="md" className="space-y-4">
                  <div className="space-y-1.5">
                    <label className="text-[10px] uppercase tracking-wider text-zinc-500" htmlFor="access-group-name">
                      Name
                    </label>
                    <ConsoleInput
                      id="access-group-name"
                      value={editor.name}
                      onChange={(event) => setEditor({ ...editor, name: event.target.value })}
                      placeholder="Access Group name"
                    />
                  </div>

                  <div className="space-y-1.5">
                    <div className="text-[10px] uppercase tracking-wider text-zinc-500">Assets</div>
                    <AssetPicker
                      assets={assets}
                      selectedPaths={editor.selectedPaths}
                      onToggle={(path) =>
                        setEditor({ ...editor, selectedPaths: toggleSelectedPath(editor.selectedPaths, path) })
                      }
                    />
                  </div>

                  <div className="space-y-1.5">
                    <div className="text-[10px] uppercase tracking-wider text-zinc-500">Members</div>
                    {unknownMemberIds.length > 0 && (
                      <div className="space-y-1 rounded-xl border border-zinc-800 bg-zinc-950/50 p-2">
                        {unknownMemberIds.map((subject) => (
                          <div
                            key={subject}
                            className="flex items-center justify-between gap-2 text-xs text-zinc-400"
                          >
                            <span>
                              unknown
                              <span className="ml-2 font-mono text-[10px] text-zinc-500">{subject}</span>
                            </span>
                            <BtnGhost
                              onClick={() =>
                                setEditor({
                                  ...editor,
                                  memberIds: editor.memberIds.filter((id) => id !== subject),
                                })
                              }
                              aria-label={`Remove unknown ${subject}`}
                            >
                              Remove
                            </BtnGhost>
                          </div>
                        ))}
                      </div>
                    )}
                    {members.length === 0 ? (
                      unknownMemberIds.length === 0 && (
                        <p className="text-xs text-zinc-500">
                          Realm members appear here when the directory can be read.
                        </p>
                      )
                    ) : (
                      <div className="max-h-48 space-y-1 overflow-y-auto rounded-xl border border-zinc-800 bg-zinc-950/50 p-2">
                        {members.map((member) => (
                          <label key={member.id} className="flex items-center gap-2 text-xs text-zinc-200">
                            <input
                              type="checkbox"
                              checked={editor.memberIds.includes(member.id)}
                              onChange={() => {
                                const memberIds = editor.memberIds.includes(member.id)
                                  ? editor.memberIds.filter((id) => id !== member.id)
                                  : [...editor.memberIds, member.id];
                                setEditor({ ...editor, memberIds });
                              }}
                            />
                            {member.displayName}
                            <span className="font-mono text-[10px] text-zinc-500">{member.username}</span>
                          </label>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="flex flex-wrap gap-2">
                    <BtnPrimary onClick={() => void saveGroup()}>Save group</BtnPrimary>
                    <BtnSecondary
                      onClick={() => {
                        setEditor(null);
                        setSaveError(null);
                      }}
                    >
                      Cancel
                    </BtnSecondary>
                  </div>
                </ConsoleCard>
              ) : (
                <ConsoleCard padding="none" className="overflow-hidden">
                  <div className="overflow-x-auto">
                    <table className="w-full border-collapse text-left text-xs">
                      <thead>
                        <tr className="border-b border-zinc-800 bg-[#0a0a0b] text-[10px] uppercase tracking-wider text-zinc-500">
                          <th className="px-3 py-2.5">Name</th>
                          <th className="px-3 py-2.5">Roots</th>
                          <th className="px-3 py-2.5">Members</th>
                          <th className="px-3 py-2.5" />
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-zinc-800">
                        {groups.length === 0 ? (
                          <tr>
                            <td colSpan={4} className="py-10 text-center text-zinc-500">
                              No Access Groups yet.
                            </td>
                          </tr>
                        ) : (
                          groups.map((group) => (
                            <tr key={group.id} className="transition-colors hover:bg-zinc-800/40">
                              <td className="px-3 py-2.5 font-semibold text-white">{group.name}</td>
                              <td className="px-3 py-2.5">
                                <div className="flex flex-wrap gap-1">
                                  {group.roots.map((root) => (
                                    <span
                                      key={root.assetId}
                                      className="rounded-md border border-zinc-700 bg-zinc-900 px-2 py-0.5 font-mono text-[9px] text-zinc-300"
                                    >
                                      {root.path}
                                    </span>
                                  ))}
                                </div>
                              </td>
                              <td className="px-3 py-2.5 tabular-nums text-zinc-300">{group.subjects.length}</td>
                              <td className="px-3 py-2.5 text-right">
                                <div className="flex justify-end gap-1">
                                  <BtnGhost onClick={() => openEdit(group)}>Edit</BtnGhost>
                                  <BtnGhost onClick={() => void deleteGroup(group)}>Delete</BtnGhost>
                                </div>
                              </td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </ConsoleCard>
              )}
            </>
          )}

          {activeSubTab === 'roles' && (
            <>
              <p className="text-xs text-zinc-500">
                These are the console&apos;s five roles and what each may open. Which role a person
                holds is decided in Keycloak; what the GraphQL service accepts from that role is
                decided by the service, not by this screen.
              </p>
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
                {(Object.keys(ROLE_CONFIGS) as UserRole[]).map((role) => {
                  const config = ROLE_CONFIGS[role];
                  return (
                    <ConsoleCard key={role} padding="sm" className="space-y-3">
                      <div className="flex items-center justify-between">
                        <span
                          className={`rounded-md border px-2.5 py-0.5 text-[10px] font-bold ${config.badgeBg} ${config.badgeText} ${config.badgeBorder}`}
                        >
                          {config.label.toUpperCase()}
                        </span>
                      </div>
                      <p className="text-[11px] leading-relaxed text-zinc-400">{config.description}</p>
                      <div className="space-y-1.5 border-t border-zinc-800 pt-2">
                        <div className="text-[9px] uppercase tracking-wider text-zinc-500">Baseline capabilities</div>
                        <div className="flex flex-wrap gap-1">
                          {SYSTEM_FEATURES.map((feat) => {
                            const isDefault = !!config.defaultPermissions[feat.key];
                            return (
                              <span
                                key={feat.key}
                                className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[9px] ${
                                  isDefault
                                    ? 'border-emerald-800/40 bg-emerald-950/40 text-emerald-400'
                                    : 'border-zinc-800 bg-zinc-950 text-zinc-600 line-through'
                                }`}
                              >
                                {feat.label}
                              </span>
                            );
                          })}
                        </div>
                      </div>
                    </ConsoleCard>
                  );
                })}
              </div>
            </>
          )}
        </PageContent>
      </div>
    </PageShell>
  );
};

# Access Groups (admin-named, Asset-scoped)

Date: 2026-09-04
Modules: `09_uns_model`, `07_uns_graphql`, `11_frontend`, `conf/keycloak/realm.json`,
`CONTEXT.md`, new ADR
Status: Approved, not yet implemented

Supersedes the “every authenticated role may read everything” decision in
[ADR-0009](../../adr/0009-oidc-authentication-for-console-and-graphql.md) §5.
Keycloak remains the authority on who exists and which Console Role they hold. This spec
adds the missing plant-authorization layer: **Access Groups** stored next to the Asset
Model.

## 1. Problem

Authentication is real. Authorization is a Console Role table on mutations, and every
signed-in role can still read the whole plant. ADR-0009 deferred per-Asset reads on
purpose: `model.asset` had no mapping from a person to a working area.

AVEVA-style plant security needs that mapping. A Security Group there is a named working
area plus a plant subtree. Ours cannot hard-code the simulator’s WTP areas
(`RawWater`, `Treatment`, `Filtration`, `Storage`, `Distribution`). Those names are one
client’s tree. The next manufacturer will call the same layer `PressShop` or `Line-7`.

`/users` is a read-only Keycloak directory: five generic people, no zone, no action
except a paragraph that says to go elsewhere. That is weaker than an admin who can
**create a group, name it, pick Assets, assign people**.

## 2. Goals

- An admin invents Access Groups by name and binds each group to one or more Asset Model
  nodes. Each chosen node covers its subtree.
- Default deny: `admin` sees the whole tree. Anyone else sees the union of their groups’
  subtrees, or nothing.
- A person may belong to several groups.
- GraphQL hides out-of-scope plant reads and refuses out-of-scope plant writes. The
  console does not enforce this.
- Users & Access grows an Access Groups tab and concrete buttons: **Create group**,
  **Assign groups**, **Open Keycloak**, **Save group**.
- Simulator seed writes example groups from *that* plant’s Area assets so the five demo
  users do not go dark. Those names are data, not an enum.

## 3. Non-goals

- Keycloak groups, group attributes, or asset paths in the access token.
- Creating or deleting Keycloak users, or changing Console Roles, from the console.
- Extra realm users beyond the five already in `realm.json`.
- MQTT / Kafka / Neo4j / Timescale / simulator-API authentication (ADR-0009 §7).
- Grafana folder or dashboard filters by Access Group.
- Attribute-level classes (Operate / SecuredWrite / VerifiedWrite / four-eyes).
- Name-matching a group to an Asset (`Packaging` does not imply `…/Packaging`).
- Per-node exceptions inside a subtree (no “Filtration except F101”).
- A third Postgres schema. Tables live in `model`.

## 4. Glossary

**Access Group**:
A name an admin typed, plus the Asset Model roots that name covers, plus the Keycloak
subjects who belong to it. The UI word is **group**.
_Avoid_: security group, zone, Keycloak group, OS group, Console Role

Realm, Console Role, and Identity keep their [CONTEXT.md](../../../CONTEXT.md) meanings.
Identity still does not carry Access Groups; those are loaded from `model` by `subject`.

## 5. Architecture

```
Keycloak  --token-->  Identity (subject, username, Console Roles)
                         |
                         v
              scope_for(identity)  -->  admin | {root paths} | empty
                         |
                         v
     covers(scope, path) on every plant read/write
                         |
                         v
              model.access_group*
              model.asset.path  (subtree = prefix)
```

| Piece | Role |
|---|---|
| Keycloak | Who exists, Console Role, login. Unpublished `:8080`; `/auth` on the console origin. |
| `Identity` | Unchanged: `subject`, `username`, `roles`. Built only by `identity_from_token`. |
| `model.access_group*` | Name, roots, members. Plant authorization. |
| `model.asset.path` | Subtree test. No recursive walk. |
| `covers` / `scope_for` | Single helpers next to `require()`. New plant fields must call them. |
| Users & Access | Admin authors groups and membership. Directory still *reads* the realm. |

Rejected alternative: store groups in Keycloak (plant structure in the IdP, no Asset
picker, token bloat). Rejected alternative: Keycloak membership + our asset list (two
writes, rename/delete sync).

## 6. Data model

Schema `model`, beside `asset`.

### `access_group`

| Column | Notes |
|---|---|
| `id` | BigInteger identity PK |
| `name` | Text, unique, non-empty after trim. Free text the admin typed. |
| `created_at` / `updated_at` | Same pattern as `metric_definition` |

### `access_group_root`

| Column | Notes |
|---|---|
| `group_id` | FK → `access_group.id` ON DELETE CASCADE |
| `asset_id` | FK → `asset.id` ON DELETE CASCADE |
| | UNIQUE `(group_id, asset_id)` |

Several roots per group are allowed. Their subtrees union.

### `access_group_member`

| Column | Notes |
|---|---|
| `group_id` | FK → `access_group.id` ON DELETE CASCADE |
| `subject` | Text, Keycloak `sub`. UNIQUE `(group_id, subject)` |

No username column. The directory already has names; a stale `subject` (user removed in
Keycloak) is shown as unknown and is removable.

### Coverage

An Asset `A` is in a group if any root `R` satisfies:

```
A.path = R.path
OR (length(A.path) > length(R.path)
    AND left(A.path, length(R.path) + 1) = R.path || '/')
```

Do **not** use `LIKE R.path || '%'`. A segment underscore would be a wildcard, which is
why `asset` already avoids `LIKE` for path checks.

A topic is in scope when its `topic_binding.asset_id` resolves to an Asset that `covers`.
A topic with no binding is **unmodelled** → admin only.

`admin` never consults these tables.

### Lifecycle

- Delete Filtration (the Asset) → that root row goes; the group remains.
- Rename a hierarchy node (prefix migrate) → `asset.path` changes, `asset_id` does not.
  Coverage follows the Asset. No rewrite of `access_group_root`.
- Delete a group → members lose only that zone (union of what remains).
- Delete a Keycloak user → member row may linger; they cannot sign in.

## 7. Enforcement

One scope per request, loaded by `Identity.subject`:

| Caller | Scope |
|---|---|
| `admin` in Console Roles | Whole plant |
| Any other role with ≥1 membership | Union of those groups’ root paths |
| Authenticated, no membership | Empty |

Reads **hide** (empty list or null, not 403):

- `getAssets`, `getAssetChildren`, `getAsset`, `getTopicContext`, `getHierarchy`
- `getUnmodelledTopics` → empty for non-admin; `getAssetModelSummary` counts only what
  the caller may see
- Graph (`getUnsNodes`, `getUnsNodesByProperty`, `getSpbNodesByMetric`), historian, OEE
- MQTT and Kafka subscriptions: accept the subscribe (the console uses wide prefixes),
  **drop** events that fail `covers`. Sparkplug topics that never bind are dropped for
  non-admin.

Writes **refuse** (`NotPermittedError`, same sentence style as `require()`):

- Alert-rule mutations when the rule’s topic is out of scope
- `assignDowntimeReason` when that event’s Asset is out of scope
- `saveHierarchy` / `retryHierarchyMigrate` stay admin-only

`recordAlertRuleEvaluation` stays callable by any signed-in role **only** for a rule
whose topic is in scope. The client only evaluates rules it was allowed to list.

Group mutations (section 8) are **admin only**.

Helpers live next to `require()`: `scope_for(identity)` and `covers(scope, path)`. A
missing call on a new plant field is a bug; a permissive default is not allowed.

## 8. GraphQL surface (Access Groups)

Queries, any authenticated **admin**:

- `getAccessGroups` → list with id, name, roots (id + path + segment + level), and
  member `subject`s. The console joins names from `fetchRealmMembers`.
- `getAccessGroup(id)` → one, or null

Mutations, `MUTATION_ROLES` rows, `admin` only:

| Field | Behaviour |
|---|---|
| `saveAccessGroup(id, name, rootAssetIds)` | Create when `id` is omitted. Trim `name`. Reject empty name, duplicate name, empty `rootAssetIds`, or an id not in `model.asset`. |
| `deleteAccessGroup(id)` | True if it existed. |
| `setAccessGroupMembers(id, subjects)` | Replace membership. Empty list is allowed (those people then see no plant data). Unknown `id` errors. Subjects are not checked against Keycloak; the admin picked them from the directory. |

`ROLE_CONFIGS` does not grow a new feature key. `/users` is already `user_management` /
admin-only.

## 9. Users & Access

Same route `/users`, still admin-only. No second page title (app header only). Tabs:

1. **User Directory** — existing columns, plus **Access groups** (chips; empty if none).
   Replace the Keycloak URL paragraph with **Open Keycloak** (opens
   `{authBaseUrl}/admin/{realm}/console/`). Per row: **Assign groups** — checklist of
   Access Groups. Save walks every group and calls `setAccessGroupMembers` with that
   group’s full member list after adding or removing this `subject`. No extra mutation.
2. **Access Groups** — name, root path chips, member count. **Create group**. Row:
   **Edit**, **Delete** (confirm; name how many people lose that zone).
3. **Role Profiles** — unchanged.

Create / Edit is one panel, not a wizard:

- **Name** — free text
- **Assets** — tree from `getAssets` (Asset Model, not `plant.yaml` / `getHierarchy`).
  Ticking a node selects that node and its subtree; descendants show as included, not as
  independent ticks
- **Members** — checklist from `fetchRealmMembers`
- **Save group** / **Cancel**

The console never writes Keycloak. It never treats `ROLE_CONFIGS` as server policy.

## 10. Demo seed

`uns_model_seed --from-simulator-config` (and the GraphQL reseed after `saveHierarchy`)
creates **one Access Group per Area Asset** in the plan. Group `name` is that Area’s
`segment` (so a PressShop plant gets `PressShop`, not WTP labels). Root is that Area.
Upsert by group name. Re-seed does not delete groups the admin created with other names.

Membership overlay, only for the pinned demo subjects in section 11:

- `engineer.user` and `auditor.user` → every Area group just upserted
- `operator.user` → the group whose root segment is `Filtration`, if it exists
- `viewer.user` → the group whose root segment is `Distribution`, if it exists
- `admin.user` → no rows

A plant without those segment names still gets Area groups; only the matching
memberships are skipped. Engineer and auditor still receive every Area group that was
upserted, so they do not go dark on a non-WTP seed.

## 11. Pinned realm subjects

`conf/keycloak/realm.json` sets stable `id` values so seed and tests can name members
without calling Keycloak:

| Username | `id` (`sub`) |
|---|---|
| `admin.user` | `00000000-0000-4000-a000-000000000001` |
| `engineer.user` | `00000000-0000-4000-a000-000000000002` |
| `operator.user` | `00000000-0000-4000-a000-000000000003` |
| `auditor.user` | `00000000-0000-4000-a000-000000000004` |
| `viewer.user` | `00000000-0000-4000-a000-000000000005` |

`00_uns_config/test/test_keycloak_realm.py` asserts these ids. Recreating the Keycloak
volume is required after the file changes (`uns_compose up -d --force-recreate uns_keycloak`).
Existing sessions die; that is expected.

## 12. Failure modes

| Condition | Behaviour |
|---|---|
| Empty or whitespace name | Rejected. Sentence: the group needs a name. |
| Duplicate name | Rejected. Sentence names the existing group. |
| Save with no roots | Rejected. A group that covers nothing is a default-deny foot-gun. |
| Root id missing from `model.asset` | Rejected. Sentence names the id. |
| Non-admin group mutation | `NotPermittedError`, same shape as today’s table. |
| Plant read out of scope | Empty or null. No 403. |
| Plant write out of scope | `NotPermittedError` naming that the Asset or topic is outside the caller’s groups. |
| Unmodelled topic | Admin only. |
| Member `subject` not in the realm | Shown as unknown; removable. |
| Admin with no Access Group rows | Sees the whole plant. |
| Engineer with no rows (seed skipped) | Sees no plant Assets. Directory chips empty. |
| MQTT subscribe to `#` | Connection stays up; out-of-scope payloads are dropped. |

## 13. Testing

No live Keycloak, no broker, no network. Tokens use the existing test-key helpers.

`09_uns_model`:

1. `covers` is true for the root, a child, and a grandchild; false for a sibling and for
   a path that only shares a prefix without a `/` boundary (`Filtration` must not cover
   `FiltrationEast`).
2. Deleting an Asset CASCADE-deletes only that root row.
3. Unique name is enforced.
4. Seed from a two-area plan upserts two groups and is idempotent.

`07_uns_graphql`:

5. `scope_for(admin)` is unrestricted; `scope_for` with no membership is empty; two
   groups union.
6. `getAssets` as operator-in-Filtration returns only that subtree.
7. `getUnmodelledTopics` as operator is empty; as admin is not.
8. MQTT handler drops an out-of-scope topic and yields an in-scope one.
9. `saveAlertRule` / `assignDowntimeReason` refuse an out-of-scope target.
10. `saveAccessGroup` / `deleteAccessGroup` / `setAccessGroupMembers` accept admin and
    reject engineer.
11. `saveAccessGroup` with no roots or a duplicate name fails with the section 12
    sentence.

`11_frontend`:

12. Directory shows Access Group chips; a member with none shows empty, not “all”.
13. **Open Keycloak** is a button (no instructional paragraph as the only CTA).
14. **Create group** / **Save group** / **Assign groups** are present and wired.
15. Ticking a parent in the picker does not require ticking children.

`00_uns_config`:

16. Realm export contains the five pinned ids.

## 14. Docs

- `CONTEXT.md` Access section: add **Access Group** (section 4). Console Role’s _Avoid_
  list still says `group` for *roles*; Access Group is the exception, written out in full
  in docs.
- ADR-0010 records: groups live in `model`, not Keycloak; default deny; subtree by
  `path`; reads hide, writes refuse. ADR-0009 gains a note that §5’s open reads are
  superseded for plant data.

## 15. Success criteria

1. An operator whose only group is Filtration cannot read `getAssets` rows under
   RawWater, and cannot save an alert rule on a RawWater topic.
2. The same operator’s MQTT feed does not surface RawWater payloads.
3. An admin with zero Access Group rows still sees the whole tree.
4. A second plant’s Area names appear as groups after seed; no Python module lists
   `RawWater` as a required group name except the optional membership overlay.
5. `/users` can create, name, root, and assign a group without opening Keycloak except
   via **Open Keycloak**.
6. ADR-0010 exists; ADR-0009 points at it.
7. HEALTH’s existing “broker is still open” line stays; this spec does not claim the
   platform is sealed.

## 16. Judgement calls

- **`subject` not username** as the member key. Usernames rename; `sub` does not. The
  directory join is a console concern.
- **Members not verified against Keycloak on save.** The admin picked from the directory.
  A stale id is inert.
- **One group per Area on seed, not per Site or Line.** Area is the AVEVA working-area
  grain and the WTP example. Admins add other grains by picking a Site or a Machine in
  the picker.
- **Hide, don’t 403, on reads.** A 403 on `getAssets` would teach the console to crash
  the tree. Empty is the scoped plant.
- **Drop MQTT events rather than refuse `#`.** The live feed already subscribes wide.
  Changing that is a console rewrite, not a security win.

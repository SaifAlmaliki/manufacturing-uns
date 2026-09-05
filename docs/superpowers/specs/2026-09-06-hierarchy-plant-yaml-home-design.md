# Hierarchy plant.yaml home

**Date:** 2026-09-06

**Owner:** `09_uns_model` (`hierarchy_io`), `99_simulator` (`read_simulator_conf`), `#/hierarchy` via `saveHierarchy`

## Decision

The ISA-95 plant tree lives at **`conf/hierarchy/plant.yaml`**. It is not a simulator file.

`#/hierarchy` is the only editor. The Asset Model seed, GraphQL, and (optionally) the internal simulator **read** this tree. The internal simulator does not own it.

## Split

| File | Contents |
| --- | --- |
| `conf/hierarchy/plant.yaml` | `enterprise`, `sites` (cells as `{ name, machines[] }`) |
| `conf/simulator/plant.yaml` | `plant`, `profiles` only (WTP scale, families, site filter) |

`saveHierarchy` writes the hierarchy file only. If `conf/simulator/plant.yaml` exists, it updates `profiles.wtp.sites` to the new site names and drops any leftover `enterprise` / `sites` keys.

## Load

1. `conf/hierarchy/plant.yaml` if present
2. Else `conf/simulator/plant.yaml` (one-release fallback for old checkouts and tests)

## Out of scope

- Portland / `*-plant.yaml` demo plants stay under `conf/simulator/`
- `hierarchy_job.yaml` stays where it is
- Instance compose overlays (`conf/instances/*/simulator/plant.yaml`) are not moved in this slice

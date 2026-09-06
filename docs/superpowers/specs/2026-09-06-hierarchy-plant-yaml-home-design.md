# Hierarchy in settings.yaml

**Date:** 2026-09-06

**Owner:** `09_uns_model` (`hierarchy_io`), `99_simulator` (`read_simulator_conf`), `#/hierarchy` via `saveHierarchy`

## Decision

The ISA-95 plant tree lives in **`conf/settings.yaml`** under `simulator.hierarchy`. That is the file production already mounts and images already copy.

`#/hierarchy` is the only editor. Seed, GraphQL, and the internal simulator **read** this block. `conf/simulator/plant.yaml` keeps only `plant` / `profiles`.

## Split

| File | Contents |
| --- | --- |
| `conf/settings.yaml` `simulator.hierarchy` | `enterprise`, `sites` (cells as `{ name, machines[] }`) |
| `conf/simulator/plant.yaml` | `plant`, `profiles` only (WTP scale, families, site filter) |

`saveHierarchy` writes `simulator.hierarchy` and derives branding / mapper filters in the same settings file. If `conf/simulator/plant.yaml` exists, it updates `profiles.wtp.sites` only.

## Load

1. `conf/settings.yaml` `simulator.hierarchy` if it names an enterprise
2. Else `conf/hierarchy/plant.yaml` (old checkout)
3. Else `conf/simulator/plant.yaml` (older checkout)

## Out of scope

- Portland / `*-plant.yaml` demo plants stay under `conf/simulator/`
- `hierarchy_job.yaml` stays where it is
- Instance compose overlays (`conf/instances/*/simulator/plant.yaml`) are not moved in this slice

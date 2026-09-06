# Hierarchy in settings.yaml

**Date:** 2026-09-06

**Owner:** `09_uns_model` (`hierarchy_io`), `#/hierarchy` via `saveHierarchy`

## Decision

The ISA-95 plant tree lives in **`conf/settings.yaml`** under `default.hierarchy`. That is the file production already mounts and images already copy. Publishers are signals on that tree, not a second plant.

`#/hierarchy` is the only editor. Seed and GraphQL **read** this block.

## Split

| File | Contents |
| --- | --- |
| `conf/settings.yaml` `default.hierarchy` | `enterprise`, `sites` (cells as `{ name, machines[] }`) |

`saveHierarchy` writes `default.hierarchy` and derives branding / mapper filters in the same settings file. Prefix-migrate job state lives in `conf/hierarchy/hierarchy_job.yaml`.

## Load

1. `conf/settings.yaml` `default.hierarchy` if it names an enterprise
2. Else `conf/hierarchy/plant.yaml` (old checkout)
3. Else `conf/simulator/plant.yaml` (older checkout)

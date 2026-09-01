# Plan extract index (Tasks 13–19)

Verbatim fenced blocks from `docs/superpowers/plans/2026-08-31-simulator-plant-model.md`.
Copy these files as-is (the YAML files already include the `# conf/simulator/...` header comments from the plan).

## Destination mapping

| Write to | Copy from |
|---|---|
| `conf/simulator/plant.yaml` | `.scratch/plan-extract-13-19/READY/conf-simulator-plant.yaml` |
| `conf/simulator/energy.yaml` | `.scratch/plan-extract-13-19/READY/conf-simulator-energy.yaml` |
| `conf/simulator/water.yaml` | `.scratch/plan-extract-13-19/READY/conf-simulator-water.yaml` |
| `conf/simulator/utilities.yaml` | `.scratch/plan-extract-13-19/READY/conf-simulator-utilities.yaml` |
| `conf/simulator/asset_health.yaml` | `.scratch/plan-extract-13-19/READY/conf-simulator-asset_health.yaml` |
| `conf/simulator/production.yaml` | `.scratch/plan-extract-13-19/READY/conf-simulator-production.yaml` |
| `conf/simulator/safety.yaml` | `.scratch/plan-extract-13-19/READY/conf-simulator-safety.yaml` |
| `99_simulator/test/test_conf_files.py` | `.scratch/plan-extract-13-19/READY/test_conf_files.py` then apply Task 17/18 table + test appends |
| `99_simulator/test/test_volume.py` | `.scratch/plan-extract-13-19/READY/test_volume.py` |
| `docs/adr/0006-simulator-plant-model-and-signal-generation.md` | `.scratch/plan-extract-13-19/READY/adr-0006.md` |
| README plant-model section | `.scratch/plan-extract-13-19/READY/README-plant-model-section.md` |

Python fragments: `task-NN-block-MM.py` in `.scratch/plan-extract-13-19/`.

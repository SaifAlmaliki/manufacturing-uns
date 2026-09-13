# Agent notes

## Orientation and local workflow

- Read `CONTEXT.md` and relevant `docs/adr/` before changing domain behavior; use the glossary's terms and flag ADR conflicts. See `docs/agents/domain.md`.
- When `graphify-out/graph.json` exists, start code exploration with `graphify query "<question>"`, `graphify path "<A>" "<B>"`, or `graphify explain "<concept>"`, then verify relevant source. Include this rule when delegating exploration. After code changes, run `graphify update .`.
- Specs: `.scratch/<feature>/spec.md`. Tickets: `.scratch/<feature>/issues/<NN>-<slug>.md`, one file per ticket. Follow `docs/agents/issue-tracker.md` and `docs/agents/triage-labels.md` for status and comments.
- User-invoked orchestrators remain explicit-only: `/grill-with-docs`, `/grill-me`, `/to-spec`, `/to-tickets`, `/implement`, `/triage`, `/wayfinder`, `/ask-matt`, `/improve-codebase-architecture`, `/handoff`, `/wait-what`.
- For compact console layouts, load `.agents/skills/console-compact-layout/SKILL.md` before designing or editing. This is the only currently checked-in local skill.

## Package boundaries

- Python requires 3.14; root `pyproject.toml` is a non-packaged dependency aggregator with editable local sources. Numbered Python modules have their own manifests, lockfiles, and pytest settings; use their `[project.scripts]` entrypoints rather than running source files directly.
- `00_uns_config` owns shared configuration and event contracts. `02_mqtt-cluster` provides both `uns_mqtt` and generated `uns_sparkplugb` support; `05_sparkplugb` is the mapper using that support.
- `07_uns_graphql` starts via `uv run uns_graphql_app`; its entrypoint is `src/uns_graphql/uns_graphql_app.py`. Asset Model schema/migrations live in `09_uns_model`; historian SQL setup lives in `04_uns_historian/sql_scripts/`.
- `11_frontend` is a separate npm project, not a root npm workspace. Root npm scripts operate the Docker stack and simulators. Frontend wiring starts at `src/main.tsx` → `src/App.tsx`.
- Sparkplug protobuf output under `02_mqtt-cluster/src/uns_sparkplugb/generated/` is generated. Change `sparkplug_b/sparkplug_b.proto` and regenerate with the bundled compiler; the exact command is in `.github/workflows/upgrade_protbuf_release.yml`.

## Commands and verification

Run Python package checks from the affected module directory to use its dependencies and pytest configuration:

```sh
uv sync
uv tool run ruff check .
uv run pytest -m "not integrationtest"
uv run pytest -m "not integrationtest" -n 0 test/<file>.py::test_name
```

- Root pytest enables `-n auto --dist loadgroup --timeout=300`; `-n 0` disables workers for a focused run. Root and module asyncio fixture scopes differ, so working directory matters.
- `integrationtest` is the service-dependent marker. Check the matching `.github/workflows/uns_*-app.yml` for service images, environment variables, and database initialization; merely starting a database is insufficient.
- Root pytest discovery omits `deploy/test`. Run its unit/contracts explicitly from root: `uv run pytest deploy/test -n 0 -v -m "not integrationtest"`. Its integration suite uses an isolated Docker topology; see `.github/workflows/cloud-edge-release.yml`.
- CI runs Ruff before pytest. Only `E9,F63,F7,F82` are blocking in `.github/include/execute_tests/action.yml`; its broader Ruff pass uses `--exit-zero`, so green CI does not mean lint-clean. Trunk owns formatter/linter versions and hooks in `.trunk/trunk.yaml`; generated directories are excluded.

From `11_frontend/`:

```sh
npm ci
npm run dev
npm run lint
npm run test:run -- src/<path>/<file>.test.tsx
npm run build
```

- `npm run lint` is **TypeScript checking only** (`tsc --noEmit`); `build` runs `tsc` then Vite. `npm test` watches; `npm run test:run` is the one-shot suite.
- Frontend tests use jsdom and `src/test/setup.ts`. Both Vite and Vitest must define `__UNS_PLATFORM_CONFIG__`; imports of the platform client depend on it at module scope.

## Configuration and stack gotchas

- Shared configuration is `conf/settings.yaml` plus untracked `conf/.secrets.yaml` (copy `conf/.secrets_template.yaml`). Python uses `uns_config.loader.get_settings()` with Dynaconf environments and `UNS_` overrides, e.g. `UNS_historian__hostname`; `UNS_CONF_DIR` overrides the configuration directory, mounted as `/app/conf` in Docker.
- Frontend `platform/settings.ts` reads the YAML `default` section at build/dev startup. It does not use the Python Dynaconf loader; restart/rebuild after changing injected settings.
- From root, `uv sync` then `npm run stack` builds/starts the local stack; `npm run down` stops it. For custom Compose commands use `uv run uns_compose -f docker-compose.yml -f docker-compose.dev.yml <args>`: the wrapper translates YAML secrets into Compose environment variables.
- `postgres.password` is the database superuser secret; `historian.password` is the application's `uns_dbuser` secret. They serve different roles in initialization and runtime connections.
- Keep the dev overlay: it passes `--skip-oee-import` because the current plant seed and OEE seed name different plants; without it, the one-shot setup can block GraphQL. Successful exits from `asset_model_setup` and `tsdb_setup_script` are expected.
- Local console: `http://localhost:8088`; GraphQL: `http://localhost:8000/graphql`. The host simulator (`npm run simulator`) needs Bash; Windows also has `scripts/run-oee-simulator.ps1`. `npm run stack:demo` runs the simulator in Docker.
- Root Compose is development-only. Production bundles and validation/install flows are in `deploy/cloud/README.md` and `deploy/edge/README.md`; release requirements live in `deploy/release-contract.json`.

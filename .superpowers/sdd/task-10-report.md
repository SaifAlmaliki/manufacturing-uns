# Task 10 Report: Secure central MQTT and route activation barrier

Branch: `feat/cloud-platform-outbound-edge`
Base: `9707e550`

## Status

**DONE**

## Summary

Implemented immutable `RouteRelease` contracts, mapper `route_control` endpoint, cloud `RouteReleaseService` with SQL lease worker, `deploy/cloud/broker` isolated-qualification config, and MQTT boundary tests. Live broker qualification remains blocked per `deploy/release-contract.json`.

## Files

| Area | Files |
|------|-------|
| Pure types | `00_uns_config/src/uns_config/route_release.py`, `test/test_route_release.py` |
| Mapper control | `06_uns_kafka/src/uns_kafka/route_control.py`, `test/test_route_control.py`; listener/config/health updates |
| Cloud service | `07_uns_graphql/src/uns_graphql/edge_api/route_release.py`, `route_release_worker.py`, `test/edge_api/test_route_release.py` |
| Persistence | `09_uns_model/migrations/versions/0012_route_release.py` |
| Broker config | `deploy/cloud/broker/README.md`, `config.xml`, `authorization/*` |
| Boundary tests | `deploy/test/test_mqtt_boundary.py` |

## Tests

```
uv run --directory 00_uns_config pytest test/test_route_release.py -v          → 9 passed
uv run --directory 06_uns_kafka pytest test/test_route_control.py -v -n 0      → 2 passed
uv run --directory 07_uns_graphql pytest test/edge_api/test_route_release.py -v -n 0 → 4 passed
uv run pytest deploy/test/test_mqtt_boundary.py -v                             → 4 passed, 3 skipped
```

Live broker integration tests skip until `release-contract.json` `qualification_status` is `qualified`.

## Activation barrier

```
stage routes → validate overlap/identity → activate mapper route+subscriptions
            → activate broker grants → verify both revisions
            → release dependent desired configuration to edge
```

Unavailable broker/mapper leaves configuration `waiting_for_routes`; previous active release continues.

## Concerns

- Live HiveMQ Enterprise broker ACL/revocation tests are documented but skipped (no qualified broker).
- Retained-bootstrap / two-broker bridge tests deferred to operator qualification harness.
- `uns_route_release_worker` uses in-memory fakes in unit tests; SQL path requires migration `0012` and running PostgreSQL.

# Central MQTT broker — isolated qualification profile

This directory contains the versioned HiveMQ Enterprise broker configuration for the
`isolated-qualification` deployment profile. It is **not** production-qualified.

## Status

| Item | Status |
| --- | --- |
| TLS 1.2/1.3 listener on TCP 8883 | Configured in `config.xml` |
| Required client certificates | Configured |
| Per-principal publish-only ACLs | Configured in `authorization/` |
| Broker administration / revocation API | Requires HiveMQ Enterprise Security Extension |
| Live broker qualification | **Blocked** — see `deploy/release-contract.json` |

`deploy/release-contract.json` records `qualification_status: unqualified` and
`broker_profile: isolated-qualification`. Real-broker boundary tests in
`deploy/test/test_mqtt_boundary.py` are skipped until an operator supplies a
digest-pinned HiveMQ Enterprise image, license, and qualified extension entitlement.

## Startup requirements

The broker refuses startup when authorization material is missing:

- `authorization/permissions.xml`
- `authorization/file-realm.xml`
- TLS keystore/truststore paths referenced from `config.xml`

Do not run this profile with anonymous MQTT enabled.

## Session parameters

| Parameter | Value |
| --- | --- |
| MQTT version | 5 |
| Clean start | `false` for bridge principals |
| Session expiry | 86400 s |
| Keep alive | 30 s |
| Max queued messages | 1000 per client |
| Persistence | enabled |

## Route activation barrier

Route releases are staged in SQL, validated in `uns_config.route_release`, then
activated in order:

1. Mapper route and subscriptions (`uns_kafka.route_control`)
2. Broker principal grants (Enterprise Security Extension administration API)
3. Revision verification
4. Release of dependent edge desired configuration

If the broker or mapper is unavailable, edge configuration remains
`waiting_for_routes` and the previous active release continues serving traffic.

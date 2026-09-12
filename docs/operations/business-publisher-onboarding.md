# Business publisher onboarding

This runbook covers generic HTTPS push for SAP-shaped, MES-shaped, LIMS-shaped, and
other business systems that cannot publish MQTT directly.

## Boundaries

- `POST /api/publications/v1/routes/{route_id}` accepts **raw body bytes** for a
  registered HTTPS route. The platform stores an explicit `uns-publication-v1`
  wrapper once and returns `202 Accepted` with a receipt ID.
- `GET /api/publications/v1/receipts/{receipt_id}` returns `queued`,
  `broker_accepted`, or `failed`. There is no `lake_delivered` status.
- HTTP `202` means **stored in the platform outbox**, not broker acceptance and not
  lake archival.
- Business identity is scoped to its registered routes. A publisher certificate
  cannot push to another principal's route.
- No reverse writeback is performed. The platform never calls back into SAP, LIMS,
  or MES systems.

## Required headers

| Header | Required | Notes |
| --- | --- | --- |
| `Idempotency-Key` | Yes | Stable per logical message; scoped to principal + route |
| `X-Occurred-At` | No | RFC3339 timestamp with timezone; validated when present |
| `X-UNS-Trusted-Proxy` | Injected by TLS proxy | Must not be supplied by clients |
| `X-Publisher-Id` | Injected by TLS proxy | Business principal ID |
| `X-Publisher-Cert-Purpose` | Injected by TLS proxy | Must be `business` |
| `X-Publisher-Cert-Serial` | Injected by TLS proxy | Certificate serial |

Do not send `X-Source-Application`, `X-Site-Id`, schema, content-type, or MQTT topic
headers. Route registration supplies immutable metadata.

## Delivery semantics

1. **Admission (`202`)** — transactional outbox insert after envelope-size and budget checks.
2. **Broker acceptance (`broker_accepted`)** — outbox worker publishes identical wrapper
   bytes with QoS 1 and confirms only after broker completion.
3. **Kafka / lake** — downstream consumers remain at-least-once; duplicates are possible.

The outbox worker keeps at most 100 leased records and 8 MiB active bytes per batch,
with 60-second renewable leases and bounded exponential retry. Configuration or auth
failures become terminal `failed` receipts requiring operator recovery.

## Idempotency window

Idempotency is scoped to publisher principal and route:

- Same key + same body/metadata → same receipt for seven days after terminal completion.
- Same key + different body → `409 Conflict`.
- After the seven-day terminal retention window expires, a repeated key is treated as new work.

## Capacity and failure behavior

- Default global queue budget: 1 GiB.
- Default per-principal budget: 128 MiB.
- Full encoded v2 envelope over 1 MiB → `413`.
- Database or capacity exhaustion before commit → `503` (no `202`).

Unresolved rows are never dropped to reclaim space.

## Source retry guidance

Sources should retry `503` and transient broker failures with the **same**
`Idempotency-Key` and identical body bytes. Poll the receipt endpoint until status is
`broker_accepted` or `failed`.

## Qualification fixtures

Contract evidence for machine, MES-shaped, LIMS-shaped, and SAP-shaped payloads is
provided by repository tests and the edge multi-system simulator. Those fixtures
validate wire contracts only; they are not connections to live vendor products.

Direct MQTT/TLS publication remains supported for systems that can use the registered
`uns-publication-v1` or raw routes without HTTPS ingress.

---
status: accepted
---

# Access Groups live in the Asset Model, not in Keycloak

Date: 2026-09-04

## Status

Accepted

## Context

ADR-0009 left every authenticated role able to read the whole plant, because
per-Asset authorization needed a mapping `model.asset` did not have.

## Decision

Access Groups are three tables in schema `model`. A group has a free-text name,
one or more Asset roots (subtree via `path`), and member subjects. GraphQL loads
scope from those tables by `Identity.subject`. `admin` bypasses them. Keycloak
does not store plant paths.

## Consequences

- Different clients name groups from their own Asset Model.
- Reads hide; writes refuse. Unmodelled topics are admin-only.
- MQTT on 1883, Grafana, and attribute-level writes remain open (ADR-0009 §7).

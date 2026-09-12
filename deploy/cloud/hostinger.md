# Hostinger VPS deployment

Deploy the production cloud bundle on a Hostinger Linux VPS using the same release
archive and contracts as AWS EC2. Provider account creation, DNS delegation, TLS
certificate issuance, and firewall changes remain human prerequisites.

## Provision

1. Create a supported Linux VPS with at least the disk budget declared in
   `release.json` (`minimum_root_disk_gb` + `minimum_data_disk_gb`).
2. Attach a data volume for Docker named volumes if the root disk is smaller than
   the declared retention budget.
3. Create public DNS records:
   - `uns.example.com` → VPS public IP (console/API/Grafana/OIDC)
   - `enroll.uns.example.com` → VPS public IP (one-time enrollment)
   - `edge-mgmt.uns.example.com` → VPS public IP (mTLS management API)
   - `mqtt.uns.example.com` → VPS public IP (MQTT TLS listener on TCP 8883)
4. Open the host firewall for TCP `443`, `80` (redirect only), and `8883`. Do not
   publish Postgres, Kafka, Neo4j, Prometheus, Grafana, Keycloak, or GraphQL ports.

## Install Docker

Install Docker Engine and the Compose plugin through the organization's approved
process. Verify `docker compose version` succeeds as the deployment user.

## Upload release

1. Transfer the verified `deploy/cloud/` bundle to `/opt/uns-cloud`.
2. Compare `release.json` digests with `docker inspect` output or registry manifests.
3. Copy `settings.yaml.example` to `settings.yaml` and set `platform.public_origin`,
   MQTT public host, and external object-store targets.
4. Populate `secrets/runtime.env`, `secrets/broker-tls.env`, `secrets/backup.env`,
   and TLS material under `secrets/tls/` and `secrets/broker-tls/`.
5. Import or pull digest-pinned images listed in `release.json`.

## Validate and start

```bash
cd /opt/uns-cloud
python3 validate.py
docker compose --env-file secrets/runtime.env -f compose.yml config --quiet
docker compose --env-file secrets/runtime.env -f compose.yml up -d
```

## Verify

1. Browse `https://uns.example.com` and sign in through OIDC.
2. Confirm Grafana dashboards load under `/grafana/`.
3. Enroll a canary edge through `enroll.uns.example.com` and verify heartbeat in the
   console.
4. From the DMZ VM, confirm MQTT TLS reaches `mqtt.uns.example.com:8883` and that
   management traffic uses `edge-mgmt.uns.example.com` with client certificates.
5. Run the backup profile on demand before declaring the host production-ready:

```bash
docker compose --env-file secrets/runtime.env --profile backup -f compose.yml run --rm cloud_backup
```

## Backup and rollback

- Scheduled backups use the `backup` profile and encrypted object-store credentials in
  `secrets/backup.env`.
- Roll back application software by deploying a previous pinned release directory
  under `releases/` and running `docker compose up -d` against that manifest.
- Roll back configuration through new desired revisions in the console; do not
  downgrade SQL or envelope readers without a qualified migration plan.

## Failure domain

This profile is a **single-server** deployment. Loss of the VPS affects console,
broker, SQL, Kafka, and object-store routing simultaneously. It is not HA and does
not substitute managed RDS, MSK, or IoT products without separate qualification.

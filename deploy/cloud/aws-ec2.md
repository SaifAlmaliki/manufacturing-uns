# AWS EC2 deployment

Deploy the production cloud bundle on a single Amazon EC2 Linux instance. The bundle,
images, and validation contracts are identical to the Hostinger VPS profile; only the
provider provisioning steps differ.

## Provision

1. Launch a supported Linux EC2 instance in the target region with instance storage
   meeting `release.json` `minimum_root_disk_gb` and attach an EBS data volume sized
   to `minimum_data_disk_gb` for Docker volumes.
2. Allocate an Elastic IP and associate it with the instance.
3. Create Route 53 (or delegated DNS) records:
   - `uns.example.com`
   - `enroll.uns.example.com`
   - `edge-mgmt.uns.example.com`
   - `mqtt.uns.example.com`
4. Configure the instance security group:
   - Allow inbound TCP `443`, `80`, and `8883` from the required client networks.
   - Deny inbound `5432`, `9092`, `7474`, `7687`, `9090`, `8000`, `8080`, and `3000`.
5. Issue TLS certificates for the console, enrollment, and management hostnames and
   install broker TLS material under `secrets/tls/` and `secrets/broker-tls/`.

## Install Docker

Install Docker Engine and the Compose plugin using the organization's approved AWS
pattern (package install or golden AMI). Confirm `docker compose version` works for
the deployment user.

## Upload release

1. Copy the verified `deploy/cloud/` bundle to `/opt/uns-cloud` (SCP, SSM, or CI).
2. Verify `release.json` image digests before first start and verify TLS files are present.
3. Copy `settings.yaml.example` to `settings.yaml` and configure:
   - `platform.public_origin`
   - `mqtt.public_host` / `mqtt.public_port`
   - `datalake.s3` bucket, region, and credentials via `secrets/runtime.env`
4. Fill `secrets/runtime.env`, `secrets/broker-tls.env`, and `secrets/backup.env`.
5. Pull or import digest-pinned images on the instance.

## Validate and start

```bash
cd /opt/uns-cloud
python3 validate.py
docker compose --env-file secrets/runtime.env -f compose.yml config --quiet
docker compose --env-file secrets/runtime.env -f compose.yml up -d
```

## Verify

1. Open `https://uns.example.com` and complete OIDC sign-in.
2. Confirm `/graphql` and embedded Grafana dashboards respond on the same origin.
3. Register and enroll a canary edge via `enroll.uns.example.com`.
4. Verify DMZ-initiated mTLS management traffic to `edge-mgmt.uns.example.com` and
   MQTT TLS to `mqtt.uns.example.com:8883`.
5. Execute an on-demand encrypted backup:

```bash
docker compose --env-file secrets/runtime.env --profile backup -f compose.yml run --rm cloud_backup
```

## Backup and rollback

- Point `secrets/backup.env` at an encrypted S3 bucket in the same or a paired region.
- Retain prior release directories under `releases/<release_id>/` for fast rollback.
- Restore drills must target an isolated environment; VM snapshots alone are not
  proof of application-consistent recovery.

## Failure domain

A single EC2 instance is one failure domain for console, broker, SQL, Kafka, and
routing state. This profile is **not HA**. Substituting RDS, MSK, Amazon MQ, or other
managed services requires separate compatibility qualification and is out of scope
for the reference bundle.

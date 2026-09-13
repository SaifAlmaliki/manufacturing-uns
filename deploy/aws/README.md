# AWS operator scripts (Windows PowerShell → Ubuntu/Amazon Linux EC2)

These scripts deploy the **split** cloud and edge bundles from a Windows workstation.
They do not replace `deploy/cloud/aws-ec2.md`; they automate the copy / Docker / build / start
steps after you have provisioned two EC2 instances.

This is a **demo / canary** path. Image digests in `release.json` are still placeholders,
HiveMQ licenses are operator-supplied, and qualification remains `unqualified`.

## What you provision (you do this in the AWS console)

| Role | Suggested size | Disk | Security group |
| --- | --- | --- | --- |
| **Cloud** | `m6i.2xlarge` or `t3.2xlarge` (8 vCPU / 32 GB) | 200 GB gp3 | Inbound: `22` from your IP, `80`, `443`, `8883`. **Deny** `5432`, `9092`, `7474`, `7687`, `8000`, `8080`, `3000`. |
| **Edge** | `t3.large` (2 vCPU / 8 GB) with `edge-sim`; `t3.medium` without | 40 GB gp3 | Inbound: `22` from your IP **only**. Outbound: `443` and `8883` to the cloud host. No inbound `8443`. |

Use Ubuntu 24.04 x86_64 AMIs. Attach an Elastic IP to the cloud instance. Create Route 53
(or other DNS) records for:

- `iip.example.com`
- `enroll.iip.example.com`
- `edge-mgmt.iip.example.com`
- `mqtt.iip.example.com`
- `publications.iip.example.com`

All of those names must resolve to the **cloud** Elastic IP.

You need:

1. An SSH key pair and the `.pem` on this Windows PC.
2. A HiveMQ Enterprise (or trial) broker image name for the cloud host.
3. A HiveMQ Edge image name for the edge host.
4. Optional `.lic` files if your images require them.
5. Optional S3 bucket + IAM user for the historic-events lake and backups.

Do **not** put cloud and edge on the same instance if you want to show outbound-only DMZ behavior.

## One-time Windows setup

OpenSSH client (`ssh`, `scp`) and `tar.exe` ship with current Windows 10/11.

```powershell
cd C:\Dev\manufacturing-uns
Copy-Item deploy\aws\uns-aws.params.example.ps1 deploy\aws\uns-aws.params.ps1
notepad deploy\aws\uns-aws.params.ps1
```

Fill `CloudHost`, `EdgeHost`, DNS names, `$env:USERPROFILE\.ssh\uns-demo.pem`, and the two HiveMQ image references.

If the `.pem` is too open, Windows OpenSSH will refuse it:

```powershell
icacls $env:USERPROFILE\.ssh\uns-demo.pem /inheritance:r
icacls $env:USERPROFILE\.ssh\uns-demo.pem /grant:r "$env:USERNAME`:R"
```

## Deploy cloud

```powershell
.\deploy\aws\Install-UnsCloud.ps1
```

That will:

1. Tar the repo (excluding `node_modules`, `.venv`, `graphify-out`) and copy it to `/opt/uns`.
2. Install Docker Engine + Compose.
3. Render `settings.yaml`, Keycloak redirect URLs, nginx server names, and secrets.
4. Create demo TLS (self-signed CA) unless `TlsMode` is `letsencrypt` or `existing`.
5. Build UNS images on the instance and pull Timescale / Kafka / Neo4j / Keycloak / Grafana / Prometheus / HiveMQ.
6. Start `deploy/cloud/compose.yml` with a generated `compose.images.yml` override (real tags, not the placeholder digests).

First image build is often 20–40 minutes.

`TlsMode=demo` will warn in browsers until you trust `deploy\aws\work\cloud-ca.crt`. For a client meeting, prefer `letsencrypt` after DNS is live.

After start, SSH and read the generated Keycloak admin password:

```text
/opt/uns/deploy/cloud/secrets/runtime.env
```

Put lake credentials in that same file (`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`), then:

```powershell
.\deploy\aws\Install-UnsCloud.ps1 -SkipSync -SkipBuild
```

## Deploy edge

Run this **after** the cloud stack is up so the script can copy the cloud CA.

```powershell
.\deploy\aws\Install-UnsEdge.ps1
```

That installs `/opt/uns-edge` via `install.sh`, builds the edge agent (and `edge-sim` images when `EnableEdgeSim` is true), and starts HiveMQ Edge + the agent. Simulators never receive the cloud broker address.

## Enroll and show data

1. Open `https://iip.example.com`, sign in, register edge id `site-01` (or your `EdgeId`).
2. Issue a one-time enrollment token.
3. From Windows:

```powershell
.\deploy\aws\Enroll-UnsEdge.ps1 -Token 'paste-the-token'
```

4. In the console, activate routes from `deploy/edge/simulation/publication-routes.yaml` and apply connections from `deploy/edge/simulation/connections.json`.
5. Label the site as simulation. Walk pending → applied, live values, then a mapping change.

Full click-path: [`docs/operations/edge-simulation-demo.md`](../../docs/operations/edge-simulation-demo.md).

## Re-running

| Flag | Effect |
| --- | --- |
| `-SkipSync` | Do not re-upload the repo tarball |
| `-SkipBuild` | Do not rebuild images |

Secrets already on the host are not overwritten with new random values.

## Honest limits

- `python3 validate.py` is **not** used here: it rejects the unqualified broker and the 700 GiB disk budget in `release.json`.
- Placeholder production digests stay in git; the EC2 override is local (`compose.images.yml`, gitignored).
- Durable Edge store-and-forward needs the HiveMQ Edge buffering license.
- Native SAP/LIMS/MES connectors and HA are out of scope.
- Do not demo from root `npm run stack`; that compose file co-locates Edge with the central services.

# Copy to uns-aws.params.ps1 in this folder and fill in. That file is gitignored.

$UnsAws = @{
  # SSH
  SshUser        = "ubuntu"
  SshKeyPath     = "$env:USERPROFILE\.ssh\uns-demo.pem"

  # Cloud EC2 public DNS or Elastic IP
  CloudHost      = "ec2-xx-xx-xx-xx.compute.amazonaws.com"

  # Edge EC2 public DNS or Elastic IP (private IP is fine if you SSH via a bastion)
  EdgeHost       = "ec2-yy-yy-yy-yy.compute.amazonaws.com"

  # DNS names that already point at the cloud Elastic IP
  ConsoleHost    = "iip.example.com"
  EnrollHost     = "enroll.iip.example.com"
  ManagementHost = "edge-mgmt.iip.example.com"
  MqttHost       = "mqtt.iip.example.com"
  PublicationsHost = "publications.iip.example.com"

  AwsRegion      = "eu-central-1"
  S3LakeBucket   = "uns-historic-events"

  # demo = self-signed CA (browser warning). letsencrypt = certbot on the cloud host.
  # existing = you already placed PEM/JKS files under deploy/cloud/secrets on the host.
  TlsMode        = "demo"
  LetsEncryptEmail = "you@example.com"

  # Required: operator-supplied HiveMQ images (trial or licensed). Do not substitute Mosquitto.
  HivemqBrokerImage = "hivemq/hivemq4:4.40.0"
  HivemqEdgeImage   = "hivemq/hivemq-edge:2025.3"
  HivemqBrokerLicensePath = ""   # optional local .lic copied to the cloud broker
  HivemqEdgeLicensePath   = ""   # optional local .lic copied to the edge host

  EdgeId         = "site-01"
  EnableEdgeSim  = $true

  RemoteRepoRoot = "/opt/uns"
  EdgeDestination = "/opt/uns-edge"
}

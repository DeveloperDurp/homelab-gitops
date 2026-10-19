# Paperclip on infra

`paperclip-infra` deploys one Paperclip instance and CloudNativePG Cluster
`paperclip-db` into infra's `paperclip` namespace. This chart deploys the
management application and database only. A separate DMZ Ashely gateway is
configured in [`dmz/ashely`](../../dmz/ashely/README.md). Local adapters execute
on the Paperclip host, so assess their access before enabling them.

| Component | Cluster | Persistent storage |
| --- | --- | --- |
| One Paperclip instance | infra | 20 GiB home on existing `nfs-client` |
| Three CNPG PostgreSQL instances | infra | 10 GiB each on existing `nfs-client` |

## Private HTTPS access

Internal DNS resolves `paperclip.internal.durp.info` to the existing DMZ
Traefik address. `dmz/internalproxy/templates/paperclip.yaml` supplies private
TLS ingress and forwards HTTPS with the original Host and explicit verified
SNI to the existing `infra-cluster` endpoint (`192.168.12.141:443`). Infra's
Paperclip ingress terminates TLS and sends HTTP to Service `paperclip:3100`.

Built-in authenticated/private mode protects the UI and API. The DMZ route
relies on admission to prepend `traefik/internal-only` and has no public
ExternalDNS record or internet-access exception. Certificates at DMZ and infra
use the existing `letsencrypt-production` ClusterIssuers. The explicit backend
ServersTransport uses `insecureSkipVerify: false`, overriding the legacy
global skip-verify setting for this route.

Hermes callbacks use this same DMZ HTTPS/443 path through normal private DNS,
with a scoped Paperclip API key. The existing LAN/VLAN allowlist includes its
three worker IPs. Verify actual pod source addresses during deployment and add
the assigned Hermes pod subnets if source IPs are retained. No separate callback
listener or infra Traefik configuration change is needed.

## Database and storage

The existing infra CloudNativePG operator (chart `0.29.1`, operator `1.30.1`)
reconciles `paperclip-db`; other databases are unchanged. The cluster has three
instances, required hostname anti-affinity and one required synchronous standby,
following the existing infra pattern. Fewer than three eligible infra nodes
can leave replicas Pending; losing every standby blocks writes. All instances
use NFS, a shared storage failure dependency.

CNPG bootstraps database/owner `paperclip`, generates Secret `paperclip-db-app`
and manages primary Service `paperclip-db-rw`. Paperclip uses its escaped `uri`
with `sslmode=verify-full`; postgres.js trusts the mounted `paperclip-db-ca`
through `NODE_EXTRA_CA_CERTS`. Only `ca.crt` is mounted. Plaintext database
connections and superuser password access are disabled. No Vault database
password is required. The database has no ingress, NodePort or LoadBalancer.

Infra's existing NFS provisioner uses `unraid.infra.durp.loc:/mnt/user/talos-infra`.
Its existing `nfs-client` StorageClass has reclaim policy `Delete` with archival
enabled; this MR does not change that shared policy. The Paperclip StatefulSet
retains its PVC on deletion/scale-down. Preserve ownership for Paperclip UID/GID
1000 and CNPG UID/GID 26; do not squash all application users to one UID.
Do not delete application or CNPG PVCs to troubleshoot startup. Arrange
independent backups and restore tests, including recovery of CNPG credentials/CA
and Paperclip signing keys.

Paperclip has a disk-backed local `/tmp` capped at 2 GiB; CNPG manages local
scratch capped at 1 GiB per database instance. Images are tagged and
digest-pinned with `imagePullPolicy: Always`. The Paperclip pod runs nonroot
and disables service-account token mounting.

## Before merge

The Applications and existing `internal-proxy` follow `main` with automatic
sync/prune/self-heal; a human merge starts reconciliation. No live changes
are performed while preparing the MR.

1. Confirm the existing infra operator/CRDs, NFS provisioner, `nfs-client` and
   Vault ClusterSecretStore are healthy. Paperclip's Application skips dry-run
   for missing CRDs and retries sync with bounded backoff; dependencies can
   still leave resources waiting until they are ready.
2. Configure private DNS for `paperclip.internal.durp.info` at DMZ ingress.
   Confirm DMZ Traefik can forward to infra ingress `192.168.12.141:443`.
   Preserve required existing DNS/Vault/certificate access. Verify actual
   source addresses/NAT before narrowing firewall rules; do not open blanket
   DMZ-to-infra access or database/Kubernetes ports. Firewall/DNS edits are
   manual prerequisites, not implemented by these charts.
3. Populate KV v2 path `kv/paperclip` through the existing Vault administration
   process, readable by infra's store, with three independent high-entropy keys:
   - `BETTER_AUTH_SECRET` for Paperclip's built-in login.
   - `PAPERCLIP_AGENT_JWT_SECRET`.
   - `PAPERCLIP_TOOL_ACTION_SIGNING_SECRET`.
   Generate each independently, e.g. `openssl rand -hex 32`, and keep values
   out of Git/logs/comments. No model-provider or gateway credentials are needed.

## First deployment

1. Verify the database has three Ready instances and a primary endpoint;
   generated app/CA Secrets and the Paperclip ExternalSecret are Ready.
   Verify `paperclip-0` and its separate application PVC are Ready.
2. Verify private DNS, TLS, DMZ source filtering and backend TLS forwarding.
   Confirm login is required and unauthenticated protected API calls are denied.
3. Open `https://paperclip.internal.durp.info`, complete first-user/login and
   company setup. Follow the [Ashely connection steps](../../dmz/ashely/README.md#connect-to-paperclip)
   to register the remote DMZ gateway.
4. Verify NFS persistence, local temporary files and authorized restart/database
   failover. Arrange CNPG-compatible database backups and separate share backups.
   ExternalSecrets refresh hourly; env credentials are read at startup, so
   authorize a workload restart after secret updates, including CNPG URI/key
   rotation. Keep signing/encryption keys stable for persisted data.

## Earlier branch deployments

If an earlier branch revision was deployed separately, preserve its data and
credentials before merging. New PVCs and a new CNPG database do not import old
data. Moving an existing deployment from DMZ to infra requires a controlled
database dump/restore and offline application-home copy. Removing an Application
may delete or orphan resources according to its deletion policy. No live
migration, resource cleanup or PVC deletion is performed here.

References: [Paperclip Docker](https://docs.paperclip.ing/reference/deploy/docker/),
[CNPG application secrets](https://cloudnative-pg.io/docs/1.30/applications/).

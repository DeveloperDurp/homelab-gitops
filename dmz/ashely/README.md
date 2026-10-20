# Ashely on DMZ

`ashely-dmz` deploys Ashely, one persistent Hermes gateway in DMZ's `ashely`
namespace. It
selects `workload=hermes`, tolerates `dedicated=hermes:NoSchedule`, and can run on
any of the three Hermes workers. Keep one writer for its SQLite home. The
Paperclip control plane/database run separately on infra; see
[`infra/paperclip/README.md`](../../infra/paperclip/README.md). This is separate
from the existing Discord-connected Hermes VM at `192.168.12.50` and its
`hermes-agent.internal.durp.info` route; neither is changed.

The gateway uses `opencode-go` / `glm-5.3-flash`. Its authenticated API is
reachable at `https://ashely.internal.durp.info` through DMZ Traefik. Private
admission applies; no public ExternalDNS record or internet-access exception is
added. Traefik discovers the gateway's pod endpoints on port 8642 through the
headless Service `ashely-headless`, without allocating a ClusterIP. An ingress
NetworkPolicy allows Traefik pods in namespace `traefik`. Confirm CNI
NetworkPolicy enforcement and Traefik labels during deployment acceptance.
Paperclip callbacks use normal private DNS and HTTPS on TCP/443 through DMZ
Traefik at `https://paperclip.internal.durp.info`, with the scoped agent key.
The existing `192.168.0.0/16` allowlist includes all three Hermes worker IPs
(`192.168.98.31`–`.33`). Same-cluster callbacks retain pod source addresses, so
its default whitelist also includes the verified node pod CIDRs:
`hermes01-dmz: 10.244.12.0/24`, `hermes02-dmz: 10.244.9.0/24`, and
`hermes03-dmz: 10.244.11.0/24`. Any pod on those dedicated nodes gains the same
private-ingress reachability; API/application authentication remains required.
Review these assigned CIDRs after node replacement; never allow all pod CIDRs.

The 10 GiB home uses DMZ's retaining `nfs-client` StorageClass, provided by the
new `nfs-dmz` Application. Its bootstrap and dynamic PVs force
`nfsvers=4.1,proto=tcp,port=2049,hard` to
`192.168.21.200:/mnt/zarray/talos-dmz`. The provisioner also selects the Hermes
pool so all NFS mount sources fit the `.31`–`.33` node firewall allowance.
The StatefulSet retains its claim on deletion or scale-down. Requests are not
server-side quotas; monitor actual share usage.

Hermes runs as UID/GID 10000, with local terminal tools in
`/opt/data/workspace`, no Kubernetes token, host mounts or container socket.
Its `/tmp` is a disk-backed local `emptyDir` capped at 2 GiB. Fresh SQLite state
uses `journal_mode: delete` and `synchronous: FULL` for NFS. Existing WAL homes
need offline conversion with all writers stopped; do not copy active databases.
The declarative config is copied into the writable home on every pod start.

Hermes runtime approval prompts are disabled with `approvals.mode: "off"` so
Paperclip-driven tasks run unattended. MCP reload and destructive session slash
command confirmations are disabled too. The API still requires its gateway
key; the container remains nonroot without host mounts or a Kubernetes token.

Init checks reject a missing/short gateway key or empty provider key before
starting the API. A pinned helper image supplies a real `tini` binary because
the Hermes image's `/usr/bin/tini` is an s6 shim. It does not run Paperclip or
receive Paperclip credentials. Gateway/helper images are digest-pinned and use
`imagePullPolicy: Always`. Arrange independent share backups and recovery tests;
NFS hard mounts can block during server/network failure.

## Persistent agent state

This starts with one default Hermes profile. Memory files under
`/opt/data/memories/`, skills under `/opt/data/skills/`, session history in
`/opt/data/state.db`, and workspace files under `/opt/data/workspace/` all live
on the retained NFS claim `ashely-data-ashely-0`. Only `/tmp` and the copied
runtime binary are ephemeral. Multiple profiles or independent agent homes
are not configured; Paperclip session keys separate conversations, not files.

## Before merge

These two new Argo Applications follow main with automatic sync/prune/self-heal.
Merging starts reconciliation. Existing infra Traefik listeners are unchanged;
no extra callback port is added. This does not create a Paperclip account or
agent automatically.

1. Create/confirm export `192.168.21.200:/mnt/zarray/talos-dmz` with NFSv4.1,
   durable writes/locking, and UID/GID 10000 writable ownership. Allow only the
   Hermes workers `192.168.98.31`–`.33` to server TCP/2049 with established
   replies, and restrict export clients accordingly. No Unraid DMZ IP or array
   maintenance is included. Infra's `talos-infra` export/provisioner is unchanged.
2. Confirm the DMZ Vault ClusterSecretStore is healthy and can read KV v2
   `kv/ashely`. Populate only this new gateway's credentials there:
   `OPENCODE_GO_API_KEY` and an independent `API_SERVER_KEY` generated with
   `openssl rand -hex 32`. Keep the existing VM's credentials separate. The
   whole record is imported; do not put unrelated secrets here.
3. Configure private DNS for `ashely.internal.durp.info` at DMZ ingress.
   Allow infra Paperclip to reach that ingress on TCP/443. The shared DMZ
   private filter must admit its actual source/NAT address; verify from the
   Paperclip pod without broadening allowed pod CIDRs. Preserve provider,
   DNS, Vault, registry and certificate access.
4. Allow Hermes callbacks to DMZ ingress TCP/443, with established replies.
   DMZ Traefik forwards to infra443 through the existing Paperclip proxy route.
   Verify the source address observed by DMZ Traefik from a real Hermes pod;
   worker sources are already allowed, while retained pod sources require their
   assigned subnets in the allowlist. Do not substitute a cluster-wide pod range.
   Firewall/DNS/export changes are manual prerequisites, not applied here.

## Connect to Paperclip

1. Verify `nfs-dmz` and `ashely-dmz` reconcile, the ExternalSecret and PVC are
   Ready, and `ashely-0` lands on a Hermes worker. Confirm DMZ Traefik can
   discover ready endpoints through the headless Service and the CNI enforces
   the ingress NetworkPolicy. Confirm API calls without a key return 401.
2. In Paperclip create an agent named `Ashely` with adapter `hermes_gateway`,
   `apiBaseUrl=https://ashely.internal.durp.info`, the new gateway key in the
   `apiKey` secret field, `sessionKeyStrategy=issue`, and
   `paperclipApiUrl=https://paperclip.internal.durp.info`. Keep insecure
   remote HTTP disabled. No database or Kubernetes API credentials are needed.
3. Mint an agent-scoped Paperclip API key and add `PAPERCLIP_API_KEY` to
   `kv/ashely`, preserving the two existing keys. ExternalSecrets refresh
   hourly and env credentials load at startup; authorize a workload restart
   after the Secret refresh. Keep this key limited to the intended company.
4. Run the adapter environment test and a small model task with an issue
   update. Verify callbacks resolve through normal private DNS and reach
   Paperclip over DMZ HTTPS/443 with valid TLS and an admitted source address.
   Confirm protected APIs still require authentication.
5. Confirm model/provider access, NFS persistence of memory and skills, local
   temporary storage, and recovery after an authorized restart. Arrange
   independent share backups. Live NFS/firewall/NAT/DNS, certificate issuance,
   endpoint discovery and CNI enforcement require deployment verification.

If an earlier gateway revision was deployed, preserve the claim, keys and
offline-consistent home before cutover. Do not mount one SQLite home from
multiple writers, copy active WAL state, or delete PVCs to make sync succeed.

Reference: [Paperclip Hermes gateway adapter](https://docs.paperclip.ing/reference/adapters/hermes-gateway/).

Unraid exports the pool path `/mnt/zarray/talos-dmz`; `/mnt/user/talos-dmz` is
a symlink and is not the exported NFS path. The provisioner uses resource name
`nfs-dmz-zarray` to create a new bootstrap PV/PVC instead of changing the old
PV's immutable NFS source. Automatic sync/prune retires the previous provisioner
and its bootstrap resources. This does not delete share files or Ashely's claims;
the StorageClass/provisioner identity stays `nfs-client` / `dmz/nfs-client`.
Existing dynamically provisioned PVs, if any, retain their original immutable
paths and need a separate migration plan; this change does not rewrite them.
This rename changes the namespace, workload, PVC name, hostname and Vault path.
If an earlier revision was deployed, preserve its old claim and credentials and
plan an explicit offline home migration before switching. New claims do not
import existing memory or skills; no live cleanup or migration is performed.

# Athens Go module proxy

Argo CD deploys this chart to the infra cluster's `athens` namespace. DMZ
terminates public TLS for `go.durp.info`, preserves the Host header, and forwards
HTTPS to the existing `infra-cluster` endpoint. Infra Traefik terminates TLS with
an internal certificate from `vault-issuer` and forwards HTTP to Athens on port
3000. The named DMZ transport sends SNI `go.durp.info` and verifies the backend
certificate using the shared `durp-internal-ca` Secret. This contains only the public
`durp.info` root certificate, sourced from the existing DMZ External Secrets CA
bundle and stored in `dmz/internalproxy/files/durp-root-ca.pem`. Rotate that file
when the internal root changes. Only DMZ uses Let's Encrypt for this service.
Other routes can reuse the same CA; see `dmz/internalproxy/README.md`.
The DMZ route uses the existing `traefik/whitelist` middleware, so clients must
reach it from the allowed private networks (including CI runners or VPN).

## Storage prerequisites

Before merging, create a dedicated `go-modules` bucket in the existing Garage
instance and a dedicated key with read/write access to that bucket only. Do not
reuse the GitLab or Harbor credentials. Athens does not create buckets.

Populate Vault KV v2 at `kv/athens` using the existing secret-management process:

| Property | Value |
| --- | --- |
| `endpoint` | `https://s3.durp.info` once the S3 ingress fix has synced and been verified |
| `region` | The instance's configured `s3_region`; verify it on Garage |
| `access-key` | Dedicated Garage access key ID |
| `secret-key` | Dedicated Garage secret access key |

The infra `vault-backend` ClusterSecretStore must be allowed to read this path.
The S3 DMZ routes forward HTTP to `192.168.21.200:3900` through the existing
`unraid` Service and endpoints, preserving the signed Host header. Verify that
the infra pods can resolve and reach the chosen endpoint. The direct URL,
`http://192.168.21.200:3900`, is an alternative using plaintext HTTP on your
private network. Do not use the Garage admin API.
External Secrets copies these four properties into `athens/athens-s3`. No secret
values belong in Git. Restart the Athens Deployment after rotating credentials;
environment variables are read when the container starts.

Athens uses path-style S3 requests and disables optional AWS SDK checksums for
S3-compatible storage. Cached module archives and metadata persist in Garage.
Downloads use ephemeral pod storage; no module-cache PVC is required. Start with
one replica and default process-local singleflight; do not enable S3 locks or
scale replicas without checking Garage's conditional-write support and Athens'
distributed locking configuration.

## Rollout and checks

Merging deploys automatically: the parent `argocd` Application and DMZ
`internal-proxy` Application follow `main` with prune and self-heal. The new
`athens` Application has the same policy. Missing Vault properties leave the
pod waiting for its Secret. This change does not modify existing buckets.

After merge, confirm the ExternalSecret is Ready, the Deployment is Available,
and both certificates are Ready. From an allowed client network, fetch a module
with an empty local cache:

```sh
task_cache=$(mktemp -d)
GOMODCACHE="$task_cache" GOPROXY=https://go.durp.info GOSUMDB=sum.golang.org \
  go mod download -json golang.org/x/text@v0.28.0
rm -rf "$task_cache"
```

Confirm objects appeared in `go-modules`, restart the pod if authorized, then
repeat with a fresh client cache to verify persistence. `/healthz` checks the
process and `/readyz` checks storage access; neither replaces a module download
and bucket check.

For developer machines and CI:

```sh
export GOPROXY=https://go.durp.info
export GOPRIVATE=gitlab.durp.info
```

Private GitLab modules are fetched directly using each client's existing GitLab
credentials. Athens downloads public modules from `proxy.golang.org` and keeps
checksum verification enabled. This is a module cache, not a compiled Go build
cache or CI artifact store.

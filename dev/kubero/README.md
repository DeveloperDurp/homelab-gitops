# Kubero (dev)

This chart vendors the upstream Kubero UI chart and the Kubero Operator v0.1.3
release manifest. The operator installs cluster-scoped CRDs and RBAC, so it is
intentionally managed without Argo CD automated pruning. Remove Kubero custom
resources before intentionally deleting this application, then remove the
operator and its CRDs under a separately reviewed teardown change.

## Secret bootstrap

The chart expects External Secrets Operator and the `vault-backend`
`ClusterSecretStore` to already be healthy in the dev cluster. Before syncing,
create `kv/kubero` in Vault with these keys:

- `webhook_secret`
- `admin_username`
- `admin_password`
- `session_key`

No credentials are stored in Git. The UI remains ClusterIP-only until a
separate ingress/TLS/Authentik change is approved and the dev prerequisites are
verified.

## Upstream sources

- UI chart source: `kubero-dev/kubero-operator`, `helm-charts/kubero`
- Operator manifest: `kubero-dev/kubero-operator` release `v0.1.3`
  (`sha256:a3dbd8f807b6c7729049a7daeb3387003f0b570f9bab17d773adef4123ee13fc`)
- UI image: `ghcr.io/kubero-dev/kubero/kubero:v3.1.1`

The upstream operator release is older than the UI image. This dev deployment
is an evaluation; validate creation of a disposable container workload before
migrating any stateful Unraid workload.

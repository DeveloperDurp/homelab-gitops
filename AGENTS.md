# Repository guide for agents

## Project structure

This repository stores Kubernetes configuration managed by Argo CD.

- `infra/`: shared infrastructure and services, including Argo CD, Forgejo,
  Harbor, CloudNativePG, Vault, and the NFS provisioner.
- `dev/`, `prd/`, `dmz/`: environment-specific Helm charts and configuration.
- `infra/argocd/templates/`: Argo CD Application manifests. Check each active
  application's source path, revision, destination cluster, and namespace before
  editing. Names alone do not identify the environment: `nfs-dev` currently
  points to `infra/nfs-provisioner`. Commented applications are not active.
- Each service chart uses `Chart.yaml` for chart metadata and dependency
  versions, `values.yaml` for overrides, and optional `templates/` for local
  resources. Dependency values belong under the dependency's name.
- `old/`: historical configuration. Do not treat it as the active deployment or
  modify it unless the task explicitly requires it.
- Environment `.gitlab/.gitlab-ci.yml` files contain OpenTofu jobs. Check that
  their referenced paths and pipeline wiring exist before relying on them.
- `renovate.json`: Renovate configuration.

## Ingress across clusters

DMZ is the ingress entry point for all clusters. Exposing a service in another
cluster requires a matching DMZ ingress route; a destination-cluster ingress
alone does not complete the traffic path.

- Add or update the hostname route in `dmz/internalproxy/templates/`, following
  an existing route to the same destination cluster.
- Reuse the destination Service and endpoints in `endpoints.yaml`. Match the
  backend port and scheme to the destination ingress and preserve the hostname.
- Include the hostname's Certificate/TLS Secret reference and external-dns
  resource using the existing patterns. Check the destination ingress accepts
  the same hostname.
- Trace the full path: DNS to DMZ, DMZ TLS and route, destination cluster ingress,
  then application Service. Render both affected charts and document live checks
  in the MR. `internal-proxy` deploys this chart to DMZ's `internalproxy` namespace.

## Required change process

1. Read the relevant files and callers. Check the working tree and preserve
   unrelated changes. Make the smallest complete change; reuse existing patterns.
2. Fetch `origin/main` and create a new `codex/<short-description>` branch before
   editing. Never commit or push directly to `main`. For a follow-up to an open
   MR, use its branch. If that MR has merged, start a new branch from current main.
3. Validate the affected configuration with focused checks. Inspect the complete
   diff and run `git diff --check` before committing. Keep credentials, rendered
   secrets, downloaded dependencies, and temporary test artifacts out of commits.
4. Commit only the requested files and push the branch. Use `glab` for GitLab
   operations, including checking MR state, creating or updating MRs, and reading
   pipeline results. Use the configured host, `gitlab.durp.info`, and repository,
   `durfy/homelab/gitops`. Do not substitute a GitHub PR or a direct main push.
5. Create an MR targeting `main` with `glab mr create`, or update the open MR
   with `glab mr update`. Describe the final behavior, validation results,
   limitations, and any migration or manual steps. Keep the title and description
   current when the requested behavior changes.
6. Return the MR link and a concise validation summary to the user. If access or
   a check is blocked, report the exact blocker; do not claim success.

**Merges are manual, after human checks.** Agents must not merge MRs, approve on
the human's behalf, enable auto-merge, or bypass review. A passing pipeline or
agent review does not authorize a merge. Leave the MR open for the human to
inspect, perform the required checks, and merge.

## Validation and deployment boundaries

- For Helm changes, use the dependency version pinned in `Chart.yaml`. Run
  `helm lint` and `helm template` with the application's actual release name,
  namespace, and values. Inspect the affected rendered resources; do not print
  secret values. Use a temporary chart copy for downloaded dependencies.
- For documentation-only changes, check referenced paths, command syntax, and
  the diff. Do not run unrelated builds or cluster tests.
- Do not claim that rendering proves live behavior. State what was checked
  locally and what the human must test after merge.
- Many Argo CD applications follow `main` with automated sync, prune, and
  self-heal. A human merge can therefore cause deployment without another manual
  sync. Check the application's policy and describe operational effects in the MR.
- An MR request does not authorize live changes. Do not run Helm installs or
  upgrades, Argo syncs, Kubernetes mutations, OpenTofu apply/destroy, or manual
  deployment jobs without explicit user authorization.
- Call out immutable-field migrations, resource recreation, data deletion, and
  effects on existing resources. Do not perform cleanup or migration to make a
  local check pass. Ask before installing tools or changing shared infrastructure.
- Keep secret values out of Git, logs, and MR text. Follow the existing Vault,
  ExternalSecret, or operator-managed Secret pattern for the affected service.

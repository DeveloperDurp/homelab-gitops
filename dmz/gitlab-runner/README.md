# Dedicated DMZ runner workers

The runner manager and its CI job pods select `workload=gitlab-runner` and
tolerate `dedicated=gitlab-runner:NoSchedule`. Both settings are required:
the chart-level selector/toleration controls the manager, while the TOML
configuration controls the job pods (including helpers and services).

Provision and verify the new DMZ workers before merging this scheduling change:

- `runner01-dmz`: 192.168.98.27, Proxmox VM9827 on mothership.
- `runner02-dmz`: 192.168.98.28, Proxmox VM9828 on overlord.
- `runner03-dmz`: 192.168.98.29, Proxmox VM9829 on vanguard.

Each has 8 vCPUs, 16 GiB RAM and a 20 GB system disk. Labels and registration
taints come from the IaC Talos patch. Normal workloads lacking this toleration
cannot schedule there; essential system DaemonSets may still run on these nodes.
This is scheduling isolation within the DMZ cluster, not a separate security
boundary for privileged CI jobs.

The Argo `gitlab-runner-dmz` Application follows `main` with automated sync,
prune and self-heal. Merging before the nodes exist leaves the manager and new
jobs Pending. Existing job pods are not moved by `NoSchedule`; let in-flight
jobs finish during rollout. The manager retains its one-hour termination grace.

The existing concurrency, build/helper/service resources, pod labels, and soft
spreading preference remain unchanged. Job data and Docker-in-Docker image
layers consume the small 20 GB root disk; monitor disk pressure and size job
concurrency accordingly.

After applying IaC, verify the three nodes are Ready with the expected labels
and taints. After merging this chart change, verify the manager and newly
created CI job pods land only on the runner nodes, including Docker-in-Docker
service pods. Confirm CNI, DNS and any required storage DaemonSets work there.

## Distributed cache

The runner uses the existing Garage endpoint at `https://s3.durp.info`.
The dedicated `gitlab-runner-cache` bucket stores project-separated cache archives.
The configuration preserves concurrency and job resources.
The configuration adds no PVC.

Complete these prerequisites before merging the cache configuration:

1. Verify the deployed Garage version supports expiration and incomplete multipart upload cleanup.
2. Create the dedicated bucket with versioning disabled.
3. Verify Garage uses the `garage` signing region shown in the existing Longhorn configuration.
4. If the region differs, update `BucketLocation` before merging.
5. Apply `cache-lifecycle.json` to this bucket through the approved S3 administration process.
6. Read back the lifecycle policy and confirm one-day expiration and one-day multipart cleanup.
7. Create a dedicated key with read and write access only to this bucket.
8. Store its `access-key` and `secret-key` properties at Vault path `kv/gitlab/runner-cache`.
9. Verify the ExternalSecret can read that path in the DMZ cluster.

Do not reuse GitLab, Harbor, Athens, or Longhorn credentials.
Keep the bucket private.
The ExternalSecret maps credentials to the chart's `accesskey` and `secretkey` fields.

Merging updates the automatically synchronized runner application.
A missing credential Secret can prevent the runner manager from starting.
Provision and verify the prerequisites before merging.

After deployment, run the same cache-enabled pipeline twice.
Confirm the first pipeline uploads its cache archive.
Confirm the second pipeline downloads and extracts that archive.
Confirm the bucket expires old objects after one day.
GitLab job artifacts use separate project retention settings.
Do not claim persistent caching works from a successful Helm render alone.

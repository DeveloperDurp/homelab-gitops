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
concurrency accordingly. No additional PVC or runner cache is added here.

After applying IaC, verify the three nodes are Ready with the expected labels
and taints. After merging this chart change, verify the manager and newly
created CI job pods land only on the runner nodes, including Docker-in-Docker
service pods. Confirm CNI, DNS and any required storage DaemonSets work there.

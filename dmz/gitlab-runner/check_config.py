"""Check values or rendered ConfigMap: python3 check_config.py [rendered.yaml]."""
from pathlib import Path
import sys
import tomllib

import yaml

values = yaml.safe_load(Path(__file__).with_name("values.yaml").read_text())["gitlab-runner"]
config = values["runners"]["config"]
if len(sys.argv) > 1:
    docs = list(yaml.safe_load_all(Path(sys.argv[1]).read_text()))
    config = next(d["data"]["config.template.toml"] for d in docs
                  if d and d.get("kind") == "ConfigMap"
                  and "config.template.toml" in d.get("data", {}))
kube = tomllib.loads(config)["runners"][0]["kubernetes"]
assert values["concurrent"] == 10
assert "builds" not in values["runners"]
for prefix, cpu, memory in [("", "500m", "1Gi"), ("helper_", "100m", "128Mi"),
                            ("service_", "500m", "512Mi")]:
    assert kube[prefix + "cpu_request"] == cpu
    assert kube[prefix + "memory_request"] == memory
    assert kube[prefix + "cpu_limit"]
    assert kube[prefix + "memory_limit"]
assert kube["cpu_limit"] == "2" and kube["memory_limit"] == "4Gi"
assert kube["cpu_limit_overwrite_max_allowed"] == "4"
assert kube["memory_limit_overwrite_max_allowed"] == "6Gi"
terms = kube["affinity"]["pod_anti_affinity"]["preferred_during_scheduling_ignored_during_execution"]
assert len(terms) == 1 and terms[0]["weight"] == 100
term = terms[0]["pod_affinity_term"]
assert term["topology_key"] == "kubernetes.io/hostname"
assert term["label_selector"]["match_labels"] == kube["pod_labels"]
print("PASS: job resources, override bounds, preferred hostname spreading, concurrency")

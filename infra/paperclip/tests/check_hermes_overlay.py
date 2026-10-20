"""Verify the rendered patch overlay and keep CI on the deployed image."""
from pathlib import Path
import subprocess

import yaml

chart = Path(__file__).resolve().parents[1]
root = chart.parents[1]
values = yaml.safe_load((chart / "values.yaml").read_text())
pipeline = yaml.safe_load((root / ".gitlab-ci.yml").read_text())
image = values["paperclip"]["image"]
assert pipeline["validate-paperclip-hermes-stream"]["image"]["name"] == image
rendered = subprocess.check_output([
    "helm", "template", "paperclip-infra", str(chart), "--namespace", "paperclip",
], text=True)
docs = list(yaml.safe_load_all(rendered))
statefulset = next(d for d in docs if d["kind"] == "StatefulSet")
template = statefulset["spec"]["template"]
spec = template["spec"]
init = spec["initContainers"][0]
app = spec["containers"][0]
assert init["image"] == app["image"] == image
assert init["securityContext"] == app["securityContext"]
assert init["imagePullPolicy"] == "Always"
assert not init.get("env") and not init.get("envFrom")
assert {v["name"] for v in init["volumeMounts"]} == {"hermes-stream-script", "hermes-stream-overlay"}
mount = next(v for v in app["volumeMounts"] if v["name"] == "hermes-stream-overlay")
assert mount == {
    "name": "hermes-stream-overlay", "mountPath": init["args"][0],
    "subPath": "execute.ts", "readOnly": True,
}
assert init["args"][1] == "/patched-hermes/execute.ts"
assert next(v for v in spec["volumes"] if v["name"] == mount["name"])["emptyDir"] == {"sizeLimit": "1Mi"}
assert len(template["metadata"]["annotations"]["checksum/hermes-stream-fix"]) == 64
config = next(d for d in docs if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "paperclip-hermes-stream-fix")
assert config["data"]["patch-hermes-gateway.mjs"] == (chart / "files/patch-hermes-gateway.mjs").read_text()
print("PASS: same deployed/CI/init image, isolated nonroot init, exact script, read-only overlay and rollout checksum")

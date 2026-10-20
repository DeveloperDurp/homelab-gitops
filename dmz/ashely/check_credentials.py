"""Render Ashely and verify required credentials reach its runtime and startup gate."""
import ast
from pathlib import Path
import subprocess
import sys

import yaml

chart = Path(__file__).resolve().parent
rendered = subprocess.check_output(
    ["helm", "template", "ashely", str(chart), "--namespace", "ashely"], text=True
)
docs = {d["kind"]: d for d in yaml.safe_load_all(rendered) if d}
external = docs["ExternalSecret"]["spec"]
secret_name = external["target"]["name"]
required = {"API_SERVER_KEY", "OPENCODE_GO_API_KEY", "PAPERCLIP_API_KEY"}
assert {d["secretKey"] for d in external["data"]} == required
vault_path = yaml.safe_load((chart / "values.yaml").read_text())["ashely"]["vaultKey"]
for entry in external["data"]:
    assert entry["remoteRef"]["key"] == vault_path
    assert entry["remoteRef"]["property"] == entry["secretKey"]
assert external["dataFrom"] == [{"extract": {"key": vault_path}}]

pod = docs["StatefulSet"]["spec"]["template"]["spec"]
init = next(c for c in pod["initContainers"] if c["name"] == "prepare-ashely")
assert {e["name"] for e in init["env"]} == required
for entry in init["env"]:
    assert entry["valueFrom"]["secretKeyRef"] == {
        "name": secret_name, "key": entry["name"]
    }
runtime = next(c for c in pod["containers"] if c["name"] == "ashely")
assert {"secretRef": {"name": secret_name}} in runtime["envFrom"]
assert not required.intersection(e["name"] for e in runtime["env"]), "Do not shadow secret values"
assert next(e["value"] for e in runtime["env"] if e["name"] == "PAPERCLIP_API_URL") == "https://paperclip.internal.durp.info"

# Exercise the actual startup guards without touching /opt/data or starting Hermes.
body = []
for node in ast.parse(init["args"][0]).body:
    if not isinstance(node, (ast.Import, ast.ImportFrom, ast.If)):
        break
    body.append(node)
assert sum(isinstance(n, ast.If) for n in body) == 3
checks = ast.unparse(ast.Module(body=body, type_ignores=[]))
valid = {
    "API_SERVER_KEY": "x" * 32,
    "OPENCODE_GO_API_KEY": "dummy-provider-key",
    "PAPERCLIP_API_KEY": "dummy-paperclip-agent-key",
}
cases = [("valid credentials", valid, True)]
for key in sorted(required):
    missing = valid.copy()
    del missing[key]
    cases.append((f"missing {key}", missing, False))
    for value in ["", "   "]:
        cases.append((f"empty/whitespace {key}", {**valid, key: value}, False))
cases.append(("short gateway key", {**valid, "API_SERVER_KEY": "x" * 31}, False))
for label, env, accepted in cases:
    result = subprocess.run([sys.executable, "-c", checks], env=env, capture_output=True)
    assert (result.returncode == 0) == accepted, label
print(f"PASS: Vault property mapping, required init refs, runtime inheritance and {len(cases)} startup credential cases")

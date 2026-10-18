"""Check DMZ access policies: python3 dmz/traefik/check_access.py [rendered-directory]."""
from collections import Counter
import argparse
import copy
import ipaddress
import json
from pathlib import Path
import re
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[2]
DMZ = ROOT / "dmz"
# Pin the pre-chain baseline so regression checks still work after this MR merges.
BASELINE = "71ea197cd12d29d6c07bfe009d41731ca8108133"
# Existing whitelist protection wins over ExternalDNS, including future DNS additions.
INTERNAL_OVERRIDES = {
    "argocd-infra-ingress", "athens", "duplicati-ingress", "durpdeploy-ingress",
    "minio-ingress", "opencode-ingress", "portainer-ingress", "proxmox-ingress",
    "root-vault-ingress", "s3-ingress", "smokeping-ingress", "tdarr-ingress",
    "unifi-ingress", "unraid-ingress", "traefik-ingress",
}


def documents(paths):
    for path in paths:
        text = path.read_text()
        # Secret/config templates need Helm; don't skip any templated HTTP route.
        if "{{" in text and "kind: IngressRoute" not in text:
            continue
        for doc in yaml.safe_load_all(text):
            if isinstance(doc, dict):
                yield doc


def check(docs):
    docs = list(docs)
    hosts = {
        h.strip()
        for d in docs if d.get("kind") == "Service"
        for h in (d.get("metadata", {}).get("annotations") or {}).get(
            "external-dns.alpha.kubernetes.io/hostname", "").split(",") if h.strip()
    }
    counts = Counter()
    for d in docs:
        if d.get("kind") != "IngressRoute":
            continue
        for route in d["spec"]["routes"]:
            exact = re.findall(r"Host\(`([^`]+)`\)", route["match"])
            public = (bool(exact) and all(h in hosts for h in exact)
                      and d["metadata"]["name"] not in INTERNAL_OVERRIDES)
            if "HostRegexp" in route["match"]:
                assert d["metadata"]["name"] == "pages-gitlab-ingress"
                assert "*.pages.durp.info" in hosts
            expected = "internet-access" if public else "internal-only"
            refs = route.get("middlewares", [])
            if public:
                assert refs and refs[0] == {"name": "internet-access", "namespace": "traefik"}, d["metadata"]["name"]
            else:
                assert not any(m.get("namespace") == "traefik" and
                               m["name"] in ["internal-only", "internet-access"] for m in refs), d["metadata"]["name"]
            counts[expected] += 1
    assert counts["internal-only"] and counts["internet-access"]
    print("PASS route assignment:", dict(counts))


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("rendered_directory", nargs="?", type=Path)
parser.add_argument("--admission-check", type=Path, help="Compiled check_defaulting.go runner")
args = parser.parse_args()
source_paths = sorted(DMZ.glob("*/templates/*.yaml"))
source_docs = list(documents(source_paths))
check(source_docs)
values = yaml.safe_load((DMZ / "traefik/values.yaml").read_text())["traefik"]
assert values["service"]["spec"]["externalTrafficPolicy"] == "Local"
assert values["providers"]["kubernetesIngress"]["enabled"] is False
assert values["ingressRoute"]["dashboard"]["enabled"] is False
assert values["ports"]["websecure"]["proxyProtocol"]["trustedIPs"] == ["10.99.0.1/32"]
mw = {d["metadata"]["name"]: d["spec"] for d in source_docs
      if d.get("kind") == "Middleware" and d["metadata"].get("namespace") == "traefik"}
assert mw["internal-only"]["chain"]["middlewares"][0]["name"] == "whitelist"
assert mw["internet-access"] == {"chain": {"middlewares": [{"name": "baseline-headers"}]}}
ranges = [ipaddress.ip_network(c) for c in mw["whitelist"]["ipAllowList"]["sourceRange"]]
for address, allowed in [("192.168.30.5", True), ("192.168.12.50", True),
                         ("10.244.6.1", False), ("10.99.0.1", False), ("1.1.1.1", False)]:
    assert any(ipaddress.ip_address(address) in n for n in ranges) == allowed
policy = next(d for d in source_docs if d.get("kind") == "ValidatingAdmissionPolicy")
assert policy["spec"]["failurePolicy"] == "Fail"
binding = next(d for d in source_docs if d.get("kind") == "ValidatingAdmissionPolicyBinding")
assert binding["spec"]["validationActions"] == ["Deny"]
mutation = next(d for d in source_docs if d.get("kind") == "MutatingAdmissionPolicy")
assert mutation["spec"]["failurePolicy"] == "Fail"
assert mutation["spec"]["reinvocationPolicy"] == "IfNeeded"
mutation_binding = next(d for d in source_docs if d.get("kind") == "MutatingAdmissionPolicyBinding")
assert mutation_binding["spec"]["policyName"] == mutation["metadata"]["name"]
assert mutation["spec"]["matchConstraints"] == policy["spec"]["matchConstraints"]
if args.admission_check:
    private = {"name": "internal-only", "namespace": "traefik"}
    public = {"name": "internet-access", "namespace": "traefik"}
    auth = {"name": "authentik-proxy-provider", "namespace": "traefik"}
    wrong_namespace = {"name": "internet-access", "namespace": "untrusted"}
    cases = []
    for name, before, after, allowed in [
        ("missing middleware", None, [private], True),
        ("empty middleware", [], [private], True),
        ("preserve app auth", [auth], [private, auth], True),
        ("explicit private", [private, auth], [private, auth], True),
        ("explicit public", [public, auth], [public, auth], True),
        ("wrong namespace is not a public opt-out", [wrong_namespace], [private, wrong_namespace], True),
        ("access chain must be first", [auth, public], [auth, public], False),
    ]:
        obj = {"spec": {"entryPoints": ["websecure"], "routes": [{"match": "Host(`test.example`)",
                "kind": "Rule", "services": [{"name": "backend", "port": 443}]}]}}
        if before is not None:
            obj["spec"]["routes"][0]["middlewares"] = before
        expected = copy.deepcopy(obj)
        expected["spec"]["routes"][0]["middlewares"] = after
        cases.append({"name": name, "object": obj, "expected": expected, "allowed": allowed})
    duplicate = copy.deepcopy(cases[0])
    duplicate["name"] = "duplicate rules get distinct patch indexes"
    for key in ["object", "expected"]:
        duplicate[key]["spec"]["routes"] *= 2
    cases.append(duplicate)
    mixed = copy.deepcopy(cases[0])
    mixed["name"] = "mixed private/public/auth rules"
    for key in ["object", "expected"]:
        mixed[key]["spec"]["routes"] += copy.deepcopy(cases[4][key]["spec"]["routes"] + cases[2][key]["spec"]["routes"])
    cases.append(mixed)
    # Exercise the actual cleaned-up manifests, not just synthetic examples.
    for doc in source_docs:
        if doc.get("kind") != "IngressRoute":
            continue
        expected = copy.deepcopy(doc)
        for route in expected["spec"]["routes"]:
            refs = route.get("middlewares", [])
            if not (refs and refs[0] == public):
                route["middlewares"] = [private] + refs
        cases.append({"name": "manifest " + doc["metadata"]["name"],
                      "object": doc, "expected": expected, "allowed": True})
    subprocess.run([str(args.admission_check.resolve())], input=json.dumps({
        "mutation": mutation["spec"]["mutations"][0]["jsonPatch"]["expression"],
        "validation": policy["spec"]["validations"][0]["expression"], "cases": cases,
    }), text=True, check=True)

# Regression guard: preserve all backend/TCP routes and existing application auth.
subprocess.run(["git", "cat-file", "-e", f"{BASELINE}^{{commit}}"], cwd=ROOT, check=True)
protected = set()
for path in source_paths:
    if "kind: IngressRoute" not in path.read_text():
        continue
    relative = str(path.relative_to(ROOT))
    result = subprocess.run(["git", "show", f"{BASELINE}:{relative}"], cwd=ROOT,
                            capture_output=True, text=True)
    if result.returncode:
        continue  # New files, including the admission policy.
    before = [d for d in yaml.safe_load_all(result.stdout) if isinstance(d, dict)]
    after = list(documents([path]))
    old_routes = {d["metadata"]["name"]: d for d in before
                  if d.get("kind") in ("IngressRoute", "IngressRouteTCP")}
    for doc in after:
        if doc.get("kind") not in ("IngressRoute", "IngressRouteTCP"):
            continue
        old = old_routes[doc["metadata"]["name"]]
        if doc["kind"] == "IngressRouteTCP":
            assert doc == old
            continue
        for a, b in zip(doc["spec"]["routes"], old["spec"]["routes"], strict=True):
            old_mw = b.get("middlewares", [])
            had_whitelist = any(x["name"] == "whitelist" and
                                x.get("namespace", old["metadata"].get("namespace")) == "traefik"
                                for x in old_mw)
            if had_whitelist:
                protected.add(doc["metadata"]["name"])
                assert not any(x["name"] == "internet-access" and x.get("namespace") == "traefik"
                               for x in a.get("middlewares", []))
            expected = [x for x in old_mw
                        if not (x["name"] == "whitelist" and x.get("namespace", "traefik") == "traefik")]
            app_middleware = [x for x in a.get("middlewares", [])
                              if not (x["name"] == "internet-access" and x.get("namespace") == "traefik")]
            assert app_middleware == expected
            assert {k: v for k, v in a.items() if k != "middlewares"} == {
                k: v for k, v in b.items() if k != "middlewares"}
        assert {k: v for k, v in doc["spec"].items() if k != "routes"} == {
            k: v for k, v in old["spec"].items() if k != "routes"}
present_routes = {d["metadata"]["name"] for d in source_docs if d.get("kind") == "IngressRoute"}
assert protected == INTERNAL_OVERRIDES & present_routes, (protected, INTERNAL_OVERRIDES & present_routes)
print(f"PASS: all {len(protected)} previously whitelisted routes remain internal-only")
apps = {d["metadata"]["name"]: d for d in documents(sorted((ROOT / "infra/argocd/templates").glob("*.yaml")))
        if d.get("kind") == "Application"}
for name in ["internal-proxy", "searxng", "traefik-dmz"]:
    options = apps[name]["metadata"]["annotations"]["argocd.argoproj.io/compare-options"]
    assert {"ServerSideDiff=true", "IncludeMutationWebhook=true"} <= set(options.split(","))
assert "ServerSideApply=true" in apps["internal-proxy"]["spec"]["syncPolicy"]["syncOptions"]
print("PASS: admission-aware ArgoCD diff and internal-proxy server-side apply")
speed_docs = list(documents([DMZ / "openspeedtest/templates/ingress.yaml"]))
speed_route = next(d for d in speed_docs if d["kind"] == "IngressRoute")
assert speed_route["spec"]["routes"][0]["services"] == [{"name": "openspeedtest", "port": 3000}]
assert len([d for d in source_docs if d.get("kind") == "IngressRoute" and
            any("Host(`speedtest.durp.info`)" in r["match"] for r in d["spec"]["routes"])]) == 1
speed_app = apps["openspeedtest"]["spec"]
assert speed_app["source"]["path"] == "dmz/openspeedtest" and "directory" not in speed_app["source"]
assert speed_app["destination"] == {"name": "dmz", "namespace": "openspeedtest"}
assert "CreateNamespace=true" in speed_app["syncPolicy"]["syncOptions"]
print("PASS: OpenSpeedTest keeps its own ingress and same-namespace Service in DMZ; Helm Application restored")
print("PASS: source-IP guardrails, fail-closed policy, preserved authentication and TCP/backends")
if args.rendered_directory:
    rendered = list(documents(sorted(args.rendered_directory.glob("*.yaml"))))
    check(rendered)
    deployment = next(d for d in rendered if d.get("kind") == "Deployment"
                      and d["metadata"]["name"] == "traefik-dmz")
    args = deployment["spec"]["template"]["spec"]["containers"][0]["args"]
    assert "--providers.kubernetesingress" not in args
    service = next(d for d in rendered if d.get("kind") == "Service"
                   and d["metadata"]["name"] == "traefik-dmz")
    assert service["spec"]["externalTrafficPolicy"] == "Local"
    print("PASS: rendered Traefik provider and source-IP settings")

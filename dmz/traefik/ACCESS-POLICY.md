# DMZ HTTP access chains

Every admitted HTTP `IngressRoute` starts with one shared middleware in namespace
`traefik`. If no access chain is specified, native mutating admission automatically
prepends `internal-only`, preserving any other application middleware. Explicit
`internet-access`, `internal-only`, or the scoped `internal-go-proxy` choice is left unchanged:

- `internal-only`: the default choice. Allows `192.168.0.0/16` LAN/VLAN clients
  and dedicated runner-node pod CIDRs `10.244.7.0/24`, `10.244.8.0/24`, and
  `10.244.5.0/24` through the shared `whitelist`, then adds `nosniff`.
  CI jobs can reach all private DMZ HTTP routes, including management UIs;
  Authentik and application authentication are not bypassed.
- `internal-go-proxy`: legacy compatibility chain for the old live Athens route
  during independent Application syncs. No source route selects it anymore:
  Athens omits access middleware and receives the default `internal-only`.
  The legacy chain allows exactly the same clients; admission still scopes it
  to `internalproxy/athens` with exact rule Host(`go.durp.info`).
- `internet-access`: explicit public exception. Adds `nosniff` without an IP
  restriction. It is NOT authentication, a WAF, or a rate limiter.

Existing application middleware follows the access chain unchanged, including
Authentik, Ollama basic auth, and Nextcloud headers. App-native authentication
remains essential for public applications.

## Choosing public routes

The user's public-app rule is the hostname annotations on ExternalDNS **Services**
(`external-dns.alpha.kubernetes.io/hostname`), matching DMZ ExternalDNS's configured
`service` source, **unless the route had the existing whitelist**. Existing whitelist
protection always wins: those routes remain internal-only even with public DNS.
Public DNS lookup alone is not used. The GitLab Pages wildcard
is an explicit exception covered by its `*.pages.durp.info` annotation.

Routes without a matching annotation are internal-only, including
`searxng.internal`, `gitlab-old`, `freshrss`, ArgoCD, Longhorn, and management UIs.
`garage.internal.durp.info` is private by default and additionally requires
Authentik before proxying to Unraid's HTTP UI on port 3909; it is not the S3 API.
There are 17 explicit public rules and 18 default-private rules in the current
sources. No route redundantly lists `internal-only` or selects the legacy Go chain.

This is explicit configuration, not a runtime DNS-based authorization decision.
When adding/removing an ExternalDNS Service annotation, review its corresponding
route's chain and run the check. Adding public DNS must not override an existing
private designation. In particular, `durpdeploy`, `go`, and `smokeping` remain
internal-only despite their ExternalDNS annotations. All 12 remaining previously
whitelisted routes are covered by the regression check. Privacy overrides are
retained for removed apps if they are reintroduced; tests do not require restoring
routes deliberately deleted from the branch. Existing extra authentication is
preserved.

## Fail-closed guard

Traefik entrypoint middleware is always prepended and cannot be bypassed by a
public route. Do not put `internal-only` on the entrypoint: public exceptions
would also be blocked.

Instead, the native Kubernetes MutatingAdmissionPolicy handles CREATE/UPDATE:

- No access middleware, an empty list, or app-only middleware: prepend
  `traefik/internal-only` to each rule that needs it.
- Explicit `traefik/internet-access`, `traefik/internal-only`, or
  `traefik/internal-go-proxy`: preserve the list; validation scopes the Go chain.
- A same-named chain in another namespace is not a public exception.
- Repeated admission is idempotent: it does not duplicate the default chain.

The ValidatingAdmissionPolicy then rejects any rule that still does not start
with a valid access chain (for example, an explicit chain placed after app auth).
Both policies fail closed on errors. No additional webhook server or controller
is deployed. Defaults do not retroactively mutate old objects; sync and inspect
all existing routes during rollout. Authorized route maintainers choose explicit
public exceptions; the policies do not query DNS or prevent administrator edits.

Source manifests list public exceptions (`internet-access`) and app-specific
middleware. All internal routes, including Athens, omit the access chain and
rely on admission defaulting.

For global runner access, sync `traefik-dmz` to update the shared allowlist.
Existing routes using `internal-only` inherit the change. Then sync
`internal-proxy` so Athens also receives the default `internal-only` chain;
backend TLS remains unchanged. Keep the legacy Go middleware compatible until
that independently synced route has migrated. No admission-policy change is
needed. Verify
real runner access to representative private routes and a Go module download;
public-VPS requests must remain 403, including spoofed forwarding headers.
These are node pod-subnet allowances, not pod-identity authorization: any pod on
those dedicated nodes has this ingress access. Review the three CIDRs after node
replacement; never add all of `10.0.0.0/8` globally. The exception does not change
firewalls, direct cluster access, raw TCP routing, DNS or authentication.
The active `internal-proxy`, `searxng`, and `traefik-dmz` Applications enable
`ServerSideDiff=true,IncludeMutationWebhook=true` so predicted state includes the
default rather than repeatedly reporting it as drift. Middleware differences are
not ignored. Check the actual admission-aware diff after rollout; new-resource
creation does not use server-side diff.

Standard Kubernetes Ingress discovery is disabled so it cannot bypass this
IngressRoute guard. The existing generated Authentik outpost Ingress becomes
unused; its explicit public callback IngressRoute remains enabled. The chart's
unprotected internal dashboard route is disabled; the custom protected dashboard
route remains.

## Original client address is required

The Traefik LoadBalancer Service uses `externalTrafficPolicy: Local` to avoid
kube-proxy source NAT. HAProxy must continue sending PROXY v2 from its trusted
WireGuard peer `10.99.0.1/32`. The trust range is not widened.

Do not add `10.244.0.0/16`, the proxy transit address, or broad private ranges back
to the allowlist to work around an incorrectly preserved source address. Only
the three explicitly trusted runner-node pod subnets are allowed; other pod
callers need a deliberate service-to-service path. Being inside Kubernetes alone
does not grant access. Runner DNS must resolve private routes to the LAN ingress;
hairpinning through the public VPS does not make its public source IP trusted.

## Validation

```bash
python3 dmz/traefik/check_access.py
# Optional: also inspect a directory of rendered Helm YAML.
python3 dmz/traefik/check_access.py /path/to/rendered-directory
```

The check verifies policy classification, original authentication, unchanged
backends/TCP rules, IP ranges, admission guards, and rendered provider/Service
settings when supplied. To exercise the exact mutation and validation CEL with
synthetic fixtures plus every actual route manifest (defaults, auth
preservation, exceptions, namespace spoofing, invalid ordering, duplicate rules,
mixed rules, and repeat admission), build the
small Go runner in a scratch module, not in this repository:

```bash
repo="$PWD" # Run from the repository root.
scratch=$(mktemp -d)
(
  cd "$scratch"
  go mod init dmz-access-check
  go get github.com/google/cel-go/ext@v0.26.1
  go build -o "$scratch/check-defaulting" "$repo/dmz/traefik/check_defaulting.go"
)
python3 dmz/traefik/check_access.py --admission-check "$scratch/check-defaulting"
```

The fixture runner models JSONPatch constructors for middleware arrays and
uses CEL's two-variable comprehensions. This is a local logic test, not proof
of a deployed Kubernetes admission chain. The DMZ API serves native v1 mutation
and validation policies; verify actual server-side dry-run behavior after sync.
The root GitLab CI job runs the source checks; the compiled CEL runner is an
additional local check.

## Rollout and acceptance checks

This is a GitOps proposal only. Keep a direct internal recovery path available.

1. **Bootstrap admission before syncing the cleaned route templates.** Install
   shared middlewares, both policies and their bindings, then verify dry-run
   defaulting before allowing application route syncs. The earlier MR commit
   `728db5f` retains explicit internal chains and contains the defaulting policy,
   so it can be deployed as the bootstrap stage before this cleanup. Coordinate
   or pause automated syncs during this first rollout: independent Applications
   do not honor each other's sync waves. Without the mutation/validation bindings
   installed, an omitted middleware is not a default and could expose the route.
   Subsequent updates can use the normal admission-aware Application syncs.
2. Verify the actual Service is `Local`, healthy Traefik endpoints exist, and
   MetalLB is advertising a node with a local Traefik endpoint. Traefik startup
   arguments must no longer include the standard Ingress provider.
3. Check admission policy status for CEL/type errors. Verify a server-side dry-run
   HTTP route without a chain gains `traefik/internal-only`, an app-auth-only rule
   gains the chain before auth, and an explicit public rule is unchanged. Repeated
   admission must not add duplicates; malformed explicit ordering must be denied.
   Native v1 mutating and validating policy resources are supported by the target
   DMZ API; the ArgoCD project/controller needs rights to deploy both cluster-scoped
   policies and bindings. If validation syncs before defaulting, omitted-chain
   requests may be rejected temporarily, but never silently become public.
4. Inspect every installed IngressRoute, including any not managed by these
   sources. Admission checks do not repair an existing unprotected object.
5. From an outside network, force the public VPS IP with the real internal Host
   and SNI. ArgoCD/Proxmox/internal SearXNG must be 403; spoofed forwarded headers
   must not change that. Logs must no longer accept a masqueraded pod-gateway IP.
6. From authorized LAN/VLAN clients and actual runner jobs, verify private
   applications pass the IP boundary while retaining their normal authentication.
   Check public GitLab clone/API, registry uploads, Pages, Authentik callbacks,
   Nextcloud, S3 and other required public applications with their normal auth.
7. Test GitLab SSH 9022 and DurpDeploy agent TLS 10943 separately. Their TCP route
   definitions and end-to-end TLS are unchanged, but Service traffic policy also
   affects those ports. HTTP middleware does not protect raw TCP listeners.

No backend TLS verification changes, CrowdSec/WAF/rate limits, firewall changes,
Talos mutations, or automatic deployments are part of this change.

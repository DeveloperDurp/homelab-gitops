# Internal backend TLS

The chart creates a shared `durp-internal-ca` Secret in the release namespace.
It contains only the public root in `files/durp-root-ca.pem`, copied from the
existing DMZ External Secrets CA bundle. Update this file when rotating the
internal root; all transports referencing the Secret will use the updated CA.

For another HTTPS backend signed by this CA, define a `ServersTransport` in
this chart and reference the shared Secret:

```yaml
apiVersion: traefik.io/v1alpha1
kind: ServersTransport
metadata:
  name: example-backend-tls
spec:
  serverName: example.durp.info
  rootCAsSecrets:
    - durp-internal-ca
```

Set `serversTransport: example-backend-tls` on the IngressRoute's backend
service, with `scheme: https` and `passHostHeader: true`. Replace the example
hostname with the backend certificate's DNS name. Separate transports preserve
each backend's SNI and hostname verification while sharing the same trust
anchor. Keep each transport in the same namespace as the CA Secret.

Athens uses `athens-backend-tls` with `serverName: go.durp.info`. Other existing
routes are unchanged; opt them in after checking their backend certificates.

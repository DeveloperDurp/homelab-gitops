"""Run with python3 infra/longhorn/check_backup.py."""
from pathlib import Path

import yaml

chart = Path(__file__).resolve().parent
values = yaml.safe_load((chart / "values.yaml").read_text())["longhorn"]
backup = values["defaultBackupStore"]
assert backup["backupTarget"] == "s3://longhorn-backups@garage/"
secret = yaml.safe_load((chart / "templates/secrets.yaml").read_text())
assert secret["kind"] == "ExternalSecret"
spec = secret["spec"]
assert spec["secretStoreRef"] == {"name": "vault-backend", "kind": "ClusterSecretStore"}
assert spec["target"]["name"] == backup["backupTargetCredentialSecret"]
assert spec["target"]["template"]["mergePolicy"] == "Merge"
assert spec["target"]["template"]["data"] == {
    "AWS_ENDPOINTS": "https://s3.durp.info", "VIRTUAL_HOSTED_STYLE": "false",
}
assert {d["secretKey"]: d["remoteRef"] for d in spec["data"]} == {
    key: {"key": "kv/longhorn/backup", "property": key}
    for key in ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"]
}
print("PASS: Garage bucket/region, HTTPS endpoint, path-style S3 and existing Vault credentials")

"""Publish only the ForgeRL route, validating and restoring Nginx on failure."""

import datetime
import hashlib
import json
import os
import subprocess
import urllib.request
from pathlib import Path


def get(url):
    with urllib.request.urlopen(url, timeout=20) as response:
        return response.status, response.read()


def main():
    assert os.geteuid() == 0
    root = Path(__file__).resolve().parents[1]
    assert get("http://127.0.0.1:18405/api/health")[0] == 200
    candidates = {
        p.resolve()
        for p in Path("/etc/nginx/sites-enabled").iterdir()
        if p.is_file() and "root /srv/portfolio/dist;" in p.read_text()
    }
    assert len(candidates) == 1
    site = candidates.pop()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = Path("/var/backups/forgerl") / stamp
    backup.mkdir(parents=True, mode=0o700)
    before = {}
    targets = {
        Path("/etc/nginx/conf.d/forgerl-zones.conf"): (
            root / "deploy/forgerl-zones.conf"
        ).read_bytes(),
        Path("/etc/nginx/snippets/forgerl.conf"): (
            root / "deploy/forgerl.conf"
        ).read_bytes(),
    }
    source = site.read_text()
    marker = "    include /etc/nginx/snippets/demo-mta-scan.conf;"
    assert source.count(marker) == 1
    if "include /etc/nginx/snippets/forgerl.conf;" not in source:
        source = source.replace(
            marker, marker + "\n    include /etc/nginx/snippets/forgerl.conf;"
        )
    targets[site] = source.encode()
    for p in targets:
        before[p] = p.read_bytes() if p.exists() else None
        if before[p] is not None:
            (backup / p.name).write_bytes(before[p])
    receipt = {"published": False, "backup": str(backup), "at": stamp}
    try:
        for p, content in targets.items():
            temporary = p.with_suffix(p.suffix + ".forgerl-new")
            temporary.write_bytes(content)
            temporary.chmod(0o644)
            temporary.replace(p)
        subprocess.run(["nginx", "-t"], check=True)
        subprocess.run(["systemctl", "reload", "nginx"], check=True)
        assert get("https://stelioszach.com/demos/forgerl/api/health")[0] == 200
        status, body = get("https://stelioszach.com/demos/forgerl/")
        assert status == 200 and b"ForgeRL" in body
        for name in ("deid", "fraud-graph", "smt-verify", "mta-scan"):
            suffix = "/api/health" if name == "mta-scan" else "/health"
            assert get("https://stelioszach.com/demos/" + name + suffix)[0] == 200
        assert get("https://stelioszach.com/")[0] == 200
        receipt.update(
            published=True,
            existing_demo_health_checks=4,
            homepage_healthy=True,
            config_hashes={
                str(p): hashlib.sha256(v).hexdigest() for p, v in targets.items()
            },
        )
    except BaseException:
        for p, content in before.items():
            if content is None:
                p.unlink(missing_ok=True)
            else:
                p.write_bytes(content)
        subprocess.run(["nginx", "-t"], check=True)
        subprocess.run(["systemctl", "reload", "nginx"], check=True)
        receipt["restored_previous_config"] = True
        (backup / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        raise
    (backup / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()

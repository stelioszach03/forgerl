"""Promote the tested read-only public service; never touch research accounting."""

import datetime
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path


def fetch(url):
    with urllib.request.urlopen(url, timeout=20) as response:
        return response.status, response.read(), dict(response.headers)


def wait_for_release():
    # A successful reload starts new workers asynchronously; an immediately
    # opened connection can still reach the draining generation.
    for attempt in range(20):
        try:
            status, data, _ = fetch("https://stelioszach.com/demos/forgerl/api/health")
            if status == 200 and json.loads(data).get("version") == "0.2.0":
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.5)
    raise RuntimeError("The public route did not converge to the tested release")


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run on the authorized portfolio host as its operator")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = Path("/var/backups/forgerl") / (stamp + "-readonly-public")
    backup.mkdir(parents=True)
    route = Path("/etc/nginx/snippets/forgerl.conf")
    original = route.read_text()
    old, new = "http://127.0.0.1:18405/", "http://127.0.0.1:18406/"
    if original.count(old) != 1:
        raise RuntimeError("Expected the existing ForgeRL route exactly once")
    status, data, headers = fetch("http://127.0.0.1:18406/api/health")
    assert status == 200 and json.loads(data)["version"] == "0.2.0"
    headers = {k.lower(): v for k, v in headers.items()}
    assert headers.get("x-content-type-options") == "nosniff"
    assert "default-src 'self'" in headers["content-security-policy"]
    (backup / "forgerl.conf").write_text(original)
    try:
        route.write_text(original.replace(old, new))
        subprocess.run(["nginx", "-t"], check=True)
        subprocess.run(["systemctl", "reload", "nginx"], check=True)
        wait_for_release()
        status, data, _ = fetch(
            "https://stelioszach.com/demos/forgerl/api/forgebench/tasks"
        )
        assert status == 200 and len(json.loads(data)["tasks"]) == 50
        status, data, _ = fetch("https://stelioszach.com/demos/forgerl/")
        assert status == 200 and b"ForgeBench" in data
        for path in (
            "/",
            "/demos/deid/health",
            "/demos/fraud-graph/health",
            "/demos/smt-verify/health",
            "/demos/mta-scan/api/health",
        ):
            assert fetch("https://stelioszach.com" + path)[0] == 200
    except BaseException:
        route.write_text(original)
        subprocess.run(["nginx", "-t"], check=True)
        subprocess.run(["systemctl", "reload", "nginx"], check=True)
        (backup / "rollback.json").write_text(json.dumps({"restored": True}))
        raise
    subprocess.run(["systemctl", "enable", "forgerl-public"], check=True)
    subprocess.run(["systemctl", "disable", "--now", "forgerl-api"], check=True)
    subprocess.run(["systemctl", "disable", "--now", "forgerl-executor"], check=True)
    receipt = {
        "published_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "public_service": "forgerl-public",
        "public_uid": "forgerl-viewer",
        "public_port": 18406,
        "catalog_tasks": 50,
        "paid_public_runs": False,
        "research_ledger_modified": False,
        "backup": str(backup),
        "existing_demo_checks": 4,
        "portfolio_check": True,
    }
    (backup / "publication.json").write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()

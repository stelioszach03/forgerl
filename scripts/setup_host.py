"""Install dedicated unprivileged identities for the ForgeRL executor.

Run once as root on the authorized portfolio VPS. Does not change existing
Docker, Nginx, firewall, SSH, medical services or the user's other applications.
"""

import json
import os
import pwd
import subprocess
from pathlib import Path


def run(args, **kw):
    return subprocess.run(args, check=True, **kw)


def main():
    assert os.geteuid() == 0
    for name, home, shell in [
        ("forgerl-api", "/var/lib/forgerl", "/usr/sbin/nologin"),
        ("forgerl-executor", "/var/lib/forgerl-executor", "/bin/bash"),
    ]:
        try:
            pwd.getpwnam(name)
        except KeyError:
            run(
                ["useradd", "--create-home", "--home-dir", home, "--shell", shell, name]
            )
    account = pwd.getpwnam("forgerl-executor")
    for name, flag in [("subuid", "--add-subuids"), ("subgid", "--add-subgids")]:
        path = Path("/etc") / name
        rows = [r.split(":") for r in path.read_text().splitlines() if r.strip()]
        if not any(r[0] == "forgerl-executor" and int(r[2]) >= 65536 for r in rows):
            start = max([200000] + [int(r[1]) + int(r[2]) for r in rows])
            run(["usermod", flag, f"{start}-{start + 65535}", "forgerl-executor"])
    run(["loginctl", "enable-linger", "forgerl-executor"])
    run(["systemctl", "start", f"user@{account.pw_uid}.service"])
    env = [
        "env",
        f"XDG_RUNTIME_DIR=/run/user/{account.pw_uid}",
        f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{account.pw_uid}/bus",
        "PATH=/usr/bin:/bin",
    ]
    run(
        [
            "runuser",
            "-u",
            "forgerl-executor",
            "--",
            *env,
            "dockerd-rootless-setuptool.sh",
            "install",
            "--force",
        ]
    )
    Path("/srv/forgerl").mkdir(mode=0o755, exist_ok=True)
    print(
        json.dumps(
            {
                "api_uid": pwd.getpwnam("forgerl-api").pw_uid,
                "executor_uid": account.pw_uid,
                "docker_socket": f"unix:///run/user/{account.pw_uid}/docker.sock",
            }
        )
    )


if __name__ == "__main__":
    main()

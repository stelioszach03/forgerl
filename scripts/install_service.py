"""Install ForgeRL services on loopback only; public Nginx activation is separate."""

import json
import os
import pwd
import secrets
import subprocess
from pathlib import Path


def run(args, **kw):
    return subprocess.run(args, check=True, **kw)


def main():
    assert os.geteuid() == 0
    base = Path("/srv/forgerl/app")
    assert (base / "forgerl/app.py").is_file()
    api = pwd.getpwnam("forgerl-api")
    exe = pwd.getpwnam("forgerl-executor")
    keydir = Path("/etc/forgerl")
    keydir.mkdir(mode=0o700, exist_ok=True)
    keydir.chmod(0o700)
    session = keydir / "session.key"
    if not session.exists():
        session.write_text(secrets.token_hex(32))
        session.chmod(0o600)
    assert (keydir / "runpod.key").is_file()
    (keydir / "runpod.key").chmod(0o600)
    data = Path("/var/lib/forgerl")
    data.mkdir(mode=0o700, exist_ok=True)
    data.chmod(0o700)
    os.chown(data, api.pw_uid, api.pw_gid)
    run(["python3", "-m", "venv", str(base / ".venv")])
    run(
        [
            str(base / ".venv/bin/pip"),
            "install",
            "--disable-pip-version-check",
            "-r",
            str(base / "requirements.lock"),
        ]
    )
    env = [
        "env",
        f"DOCKER_HOST=unix:///run/user/{exe.pw_uid}/docker.sock",
        f"XDG_RUNTIME_DIR=/run/user/{exe.pw_uid}",
    ]
    run(
        [
            "runuser",
            "-u",
            "forgerl-executor",
            "--",
            *env,
            "docker",
            "build",
            "--pull",
            "-t",
            "forgerl-sandbox:v1",
            str(base / "sandbox"),
        ]
    )
    image = subprocess.check_output(
        [
            "runuser",
            "-u",
            "forgerl-executor",
            "--",
            *env,
            "docker",
            "image",
            "inspect",
            "forgerl-sandbox:v1",
            "--format",
            "{{.Id}}",
        ],
        text=True,
    ).strip()
    assert image.startswith("sha256:")
    (keydir / "sandbox-image").write_text(image + "\n")
    broker = f"""[Unit]
Description=ForgeRL restricted sandbox broker (rootless Docker)
After=user@{exe.pw_uid}.service
Requires=user@{exe.pw_uid}.service

[Service]
Type=simple
User=forgerl-executor
Group=forgerl-api
WorkingDirectory={base}
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=DOCKER_HOST=unix:///run/user/{exe.pw_uid}/docker.sock
Environment=XDG_RUNTIME_DIR=/run/user/{exe.pw_uid}
Environment=FORGERL_EXECUTOR_ALLOWED_UIDS={api.pw_uid},0
Environment=FORGERL_SANDBOX_IMAGE={image}
ExecStart={base}/.venv/bin/python -m forgerl.sandbox --serve /run/forgerl-executor/executor.sock
RuntimeDirectory=forgerl-executor
RuntimeDirectoryMode=0750
UMask=0007
Restart=on-failure
RestartSec=3
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=yes
RestrictAddressFamilies=AF_UNIX
ReadWritePaths=/run/forgerl-executor
MemoryMax=256M
TasksMax=64

[Install]
WantedBy=multi-user.target
"""
    web = f"""[Unit]
Description=ForgeRL evidence workbench
After=network-online.target forgerl-executor.service
Requires=forgerl-executor.service

[Service]
Type=simple
User=forgerl-api
Group=forgerl-api
WorkingDirectory={base}
LoadCredential=runpod-key:/etc/forgerl/runpod.key
LoadCredential=session-key:/etc/forgerl/session.key
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=FORGERL_PUBLIC_ORIGIN=https://stelioszach.com
Environment=FORGERL_DB=/var/lib/forgerl/forgerl.sqlite3
Environment=FORGERL_POLICY_FILE={base}/artifacts/policy.json
Environment=FORGERL_BENCHMARK_FILE={base}/artifacts/benchmark.json
Environment=FORGERL_EXECUTOR_SOCKET=/run/forgerl-executor/executor.sock
ExecStart={base}/.venv/bin/uvicorn forgerl.app:app --host 127.0.0.1 --port 18405 --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-access-log
Restart=on-failure
RestartSec=3
TimeoutStopSec=15
UMask=0077
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
ReadWritePaths=/var/lib/forgerl
MemoryMax=512M
CPUQuota=100%
TasksMax=64

[Install]
WantedBy=multi-user.target
"""
    for name, value in [("forgerl-executor", broker), ("forgerl-api", web)]:
        (Path("/etc/systemd/system") / (name + ".service")).write_text(value)
    run(["systemctl", "daemon-reload"])
    run(
        [
            "systemctl",
            "enable",
            "--now",
            "forgerl-executor.service",
            "forgerl-api.service",
        ]
    )
    print(
        json.dumps(
            {
                "installed": True,
                "bind": "127.0.0.1:18405",
                "sandbox_image": image,
                "nginx_changed": False,
            }
        )
    )


if __name__ == "__main__":
    main()

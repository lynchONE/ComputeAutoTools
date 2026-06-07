from __future__ import annotations

from getpass import getuser
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Optional

from .config import ConnectionConfig


@dataclass
class SshTarget:
    host: str
    port: int
    user: str


@dataclass
class ConnectionCheckResult:
    ok: bool
    mode: str
    detail: str


def check_connection(
    target: SshTarget,
    config: ConnectionConfig,
    command_timeout_seconds: float | None = None,
) -> ConnectionCheckResult:
    return _check_ssh(target, config, command_timeout_seconds)


def _check_ssh(
    target: SshTarget,
    config: ConnectionConfig,
    command_timeout_seconds: float | None,
) -> ConnectionCheckResult:
    if command_timeout_seconds is not None and command_timeout_seconds <= 0:
        return ConnectionCheckResult(ok=False, mode="ssh", detail="ssh command timed out before start")
    key_path: Optional[Path] = None
    temp_key_path: Optional[Path] = None
    if config.ssh_private_key_path.strip():
        key_path = Path(config.ssh_private_key_path).expanduser()
        if not key_path.is_file():
            return ConnectionCheckResult(ok=False, mode="ssh", detail=f"ssh private key not found: {key_path}")
    elif config.ssh_private_key.strip():
        temp_key_path = _write_temp_private_key(config.ssh_private_key)
        key_path = temp_key_path
    else:
        return ConnectionCheckResult(ok=False, mode="ssh", detail="ssh private key path or private key is required")

    ssh_connect_timeout = config.connect_timeout_seconds
    process_timeout = float(config.connect_timeout_seconds + 5)
    if command_timeout_seconds is not None:
        ssh_connect_timeout = min(ssh_connect_timeout, max(1, int(command_timeout_seconds)))
        process_timeout = min(process_timeout, command_timeout_seconds)

    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        f"ConnectTimeout={ssh_connect_timeout}",
        "-p",
        str(target.port),
    ]
    command.extend(["-i", str(key_path)])
    command.append(f"{target.user}@{target.host}")
    command.append(config.ssh_command)

    try:
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=process_timeout,
            )
        except FileNotFoundError:
            return ConnectionCheckResult(ok=False, mode="ssh", detail="ssh executable not found")
        except subprocess.TimeoutExpired:
            return ConnectionCheckResult(ok=False, mode="ssh", detail=f"ssh command timed out after {process_timeout:g} seconds")
    finally:
        if temp_key_path is not None:
            temp_key_path.unlink(missing_ok=True)

    if completed.returncode == 0:
        return ConnectionCheckResult(ok=True, mode="ssh", detail="ssh command succeeded")

    stderr = completed.stderr.strip()
    stdout = completed.stdout.strip()
    detail = stderr if stderr else stdout
    if not detail:
        detail = f"ssh exited with code {completed.returncode}"
    return ConnectionCheckResult(ok=False, mode="ssh", detail=detail)


def _write_temp_private_key(private_key: str) -> Path:
    with NamedTemporaryFile("w", encoding="utf-8", delete=False, prefix="vast-auto-ssh-", suffix=".key") as handle:
        handle.write(private_key.strip())
        handle.write("\n")
        temp_path = Path(handle.name)
    os.chmod(temp_path, 0o600)
    if os.name == "nt":
        _restrict_windows_private_key(temp_path)
    return temp_path


def _restrict_windows_private_key(path: Path) -> None:
    commands = [
        ["icacls", str(path), "/inheritance:r"],
        ["icacls", str(path), "/grant:r", f"{getuser()}:R"],
    ]
    for command in commands:
        subprocess.run(command, check=False, capture_output=True, text=True)

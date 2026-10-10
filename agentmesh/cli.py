from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
import tomllib
import webbrowser
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from urllib.parse import urlparse

import httpx
import keyring
from keyring.errors import KeyringError
from platformdirs import user_config_path

from agentmesh.runner_client import RunnerControlPlaneClient
from agentmesh.runner_contracts import RunnerCapabilitiesV1
from agentmesh.runner_service import LocalRunnerService
from agentmesh.runner_tools import available_local_tool_names

_KEYRING_SERVICE = "agentmesh.runner"


class RunnerCliError(RuntimeError):
    pass


def package_version() -> str:
    try:
        return version("agentmesh")
    except PackageNotFoundError:
        return "0.1.0"


def local_capabilities() -> RunnerCapabilitiesV1:
    return RunnerCapabilitiesV1(
        platform=platform.system().lower() or "unknown",
        architecture=platform.machine().lower() or "unknown",
        runner_version=package_version(),
        tools=available_local_tool_names(),
        model_capabilities=['structured-session-v1', 'context-handoff-v1', 'tool-handoff-v1'],
    )


def _config_path() -> Path:
    configured = os.getenv("AGENTMESH_CONFIG_PATH", "").strip()
    return Path(configured).expanduser() if configured else user_config_path("agentmesh") / "config.toml"


def _load_config() -> dict[str, str]:
    path = _config_path()
    if not path.is_file():
        return {}
    with path.open("rb") as stream:
        raw = tomllib.load(stream)
    runner = raw.get("runner")
    if not isinstance(runner, dict):
        return {}
    return {
        key: value
        for key in ("server_url", "runner_id")
        if isinstance((value := runner.get(key)), str) and value.strip()
    }


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _save_config(*, server_url: str, runner_id: str) -> None:
    path = _config_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    content = f"[runner]\nserver_url = {_toml_string(server_url)}\nrunner_id = {_toml_string(runner_id)}\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def _credential_account(server_url: str, runner_id: str) -> str:
    return f"{urlparse(server_url).netloc}:{runner_id}"


def _store_runner_token(server_url: str, runner_id: str, token: str) -> None:
    try:
        keyring.set_password(_KEYRING_SERVICE, _credential_account(server_url, runner_id), token)
    except KeyringError as error:
        raise RunnerCliError("Unable to save the Runner credential in the operating-system keyring") from error


def _server_url(value: str | None, config: dict[str, str]) -> str:
    server = (value or os.getenv("AGENTMESH_SERVER_URL", "") or config.get("server_url", "")).strip().rstrip("/")
    parsed = urlparse(server)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RunnerCliError("AgentMesh server URL is required and must use http or https")
    return server


def _runner_token(server_url: str, config: dict[str, str]) -> str:
    token = os.getenv("AGENTMESH_RUNNER_TOKEN", "").strip()
    if token:
        return token
    runner_id = config.get("runner_id", "")
    if not runner_id:
        raise RunnerCliError("Runner is not enrolled; run `agentmesh setup` first")
    try:
        token = keyring.get_password(_KEYRING_SERVICE, _credential_account(server_url, runner_id)) or ""
    except KeyringError as error:
        raise RunnerCliError("Unable to read the Runner credential from the operating-system keyring") from error
    if not token:
        raise RunnerCliError("Runner credential is missing; run `agentmesh setup` again")
    return token


def runner_doctor(args: argparse.Namespace) -> int:
    capabilities = local_capabilities()
    config = _load_config()
    server = (args.server or os.getenv("AGENTMESH_SERVER_URL", "") or config.get("server_url", "")).strip()
    credential_configured = bool(os.getenv("AGENTMESH_RUNNER_TOKEN", "").strip())
    if not credential_configured and server and config.get("runner_id"):
        try:
            credential_configured = bool(
                keyring.get_password(
                    _KEYRING_SERVICE,
                    _credential_account(server, config["runner_id"]),
                )
            )
        except KeyringError:
            credential_configured = False
    payload = {
        "status": "ok",
        "server": server or None,
        "runner_id": config.get("runner_id"),
        "runner_token_configured": credential_configured,
        "capabilities": capabilities.model_dump(mode="json"),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def runner_setup(args: argparse.Namespace) -> int:
    server = _server_url(args.server, {})
    capabilities = local_capabilities()
    device_name = args.name.strip() if args.name else platform.node().strip() or "AgentMesh Runner"
    try:
        with httpx.Client(timeout=args.timeout) as client:
            started = client.post(
                f"{server}/api/runner/enrollment/start",
                json={"device_name": device_name, "capabilities": capabilities.model_dump(mode="json")},
            )
            started.raise_for_status()
            enrollment = started.json()
            verification_uri = str(enrollment["verification_uri"])
            user_code = str(enrollment["user_code"])
            device_code = str(enrollment["device_code"])
            interval = max(1, int(enrollment.get("interval", 2)))
            expires_in = max(1, int(enrollment.get("expires_in", 600)))
            print(f"Open: {verification_uri}")
            print(f"Code: {user_code}")
            if not args.no_browser:
                webbrowser.open(verification_uri)

            deadline = time.monotonic() + expires_in
            while time.monotonic() < deadline:
                exchanged = client.post(
                    f"{server}/api/runner/enrollment/token",
                    json={"device_code": device_code},
                )
                exchanged.raise_for_status()
                token_payload = exchanged.json()
                if token_payload.get("status") == "approved":
                    runner = token_payload.get("runner")
                    token = token_payload.get("access_token")
                    runner_id = runner.get("id") if isinstance(runner, dict) else None
                    if not isinstance(runner_id, str) or not isinstance(token, str):
                        raise RunnerCliError("Runner enrollment response is incomplete")
                    _store_runner_token(server, runner_id, token)
                    _save_config(server_url=server, runner_id=runner_id)
                    print(f"Runner enrolled: {runner_id}")
                    return 0
                time.sleep(interval)
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
        raise RunnerCliError(f"Runner enrollment failed: {error}") from error
    raise RunnerCliError("Runner enrollment expired before it was approved")


def runner_start(args: argparse.Namespace) -> int:
    config = _load_config()
    server = _server_url(args.server, config)
    token = _runner_token(server, config)
    if args.interval <= 0 or args.timeout <= 0:
        raise RunnerCliError("Runner interval and timeout must be greater than zero")
    try:
        with RunnerControlPlaneClient(server, token, timeout=args.timeout) as client:
            service = LocalRunnerService(client, capabilities=local_capabilities())
            while True:
                claimed = service.run_once()
                print(json.dumps({"status": "processed" if claimed else "connected"}, ensure_ascii=False))
                if args.once:
                    return 0
                time.sleep(0 if claimed else args.interval)
    except KeyboardInterrupt:
        return 0
    except (httpx.HTTPError, RunnerCliError) as error:
        print(f"agentmesh runner: {error}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentmesh")
    parser.add_argument("--version", action="version", version=f"%(prog)s {package_version()}")
    commands = parser.add_subparsers(dest="command", required=True)

    setup = commands.add_parser("setup", help="Enroll this device as an AgentMesh Runner")
    setup.add_argument("--server", required=True)
    setup.add_argument("--name")
    setup.add_argument("--timeout", type=float, default=10.0)
    setup.add_argument("--no-browser", action="store_true")
    setup.set_defaults(handler=runner_setup)

    runner = commands.add_parser("runner", help="Manage the local AgentMesh Runner")
    runner_commands = runner.add_subparsers(dest="runner_command", required=True)

    doctor = runner_commands.add_parser("doctor", help="Inspect local Runner capabilities")
    doctor.add_argument("--server")
    doctor.set_defaults(handler=runner_doctor)

    start = runner_commands.add_parser("start", help="Start the local Runner loop")
    start.add_argument("--server")
    start.add_argument("--interval", type=float, default=20.0)
    start.add_argument("--timeout", type=float, default=10.0)
    start.add_argument("--once", action="store_true")
    start.set_defaults(handler=runner_start)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except RunnerCliError as error:
        print(f"agentmesh: {error}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

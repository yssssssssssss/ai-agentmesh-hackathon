from __future__ import annotations

import argparse

from agentmesh import cli


class _Response:
    def __init__(self, payload: dict[str, object]):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


class _EnrollmentClient:
    def __init__(self, *, timeout: float):
        assert timeout == 5.0
        self.calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def post(self, url: str, *, json: dict[str, object]):
        self.calls += 1
        if url.endswith("/api/runner/enrollment/start"):
            assert json["device_name"] == "Test Mac"
            return _Response(
                {
                    "device_code": "device-secret-value-with-enough-entropy",
                    "user_code": "ABCD-2345",
                    "verification_uri": "https://mesh.example.com/admin?section=runners&runner_enrollment=ABCD-2345",
                    "expires_in": 600,
                    "interval": 2,
                }
            )
        assert url.endswith("/api/runner/enrollment/token")
        return _Response(
            {
                "status": "approved",
                "runner": {"id": "runner_123"},
                "access_token": "device-secret-value-with-enough-entropy",
            }
        )


def test_runner_setup_saves_non_secret_config_and_keyring_token(tmp_path, monkeypatch, capsys) -> None:
    config_path = tmp_path / "config.toml"
    stored: dict[tuple[str, str], str] = {}
    monkeypatch.setenv("AGENTMESH_CONFIG_PATH", str(config_path))
    monkeypatch.setattr(cli.httpx, "Client", _EnrollmentClient)
    monkeypatch.setattr(cli.webbrowser, "open", lambda _url: True)
    monkeypatch.setattr(
        cli.keyring,
        "set_password",
        lambda service, account, token: stored.__setitem__((service, account), token),
    )

    result = cli.runner_setup(
        argparse.Namespace(
            server="https://mesh.example.com/",
            name="Test Mac",
            timeout=5.0,
            no_browser=True,
        )
    )

    assert result == 0
    assert cli._load_config() == {
        "server_url": "https://mesh.example.com",
        "runner_id": "runner_123",
    }
    assert config_path.stat().st_mode & 0o777 == 0o600
    assert stored[("agentmesh.runner", "mesh.example.com:runner_123")] == ("device-secret-value-with-enough-entropy")
    assert "device-secret-value-with-enough-entropy" not in capsys.readouterr().out


def test_runner_start_once_uses_saved_runner_credential(tmp_path, monkeypatch, capsys) -> None:
    config_path = tmp_path / "config.toml"
    monkeypatch.setenv("AGENTMESH_CONFIG_PATH", str(config_path))
    cli._save_config(server_url="https://mesh.example.com", runner_id="runner_123")
    monkeypatch.delenv("AGENTMESH_RUNNER_TOKEN", raising=False)
    monkeypatch.setattr(cli.keyring, "get_password", lambda _service, _account: "runner-token")

    class Client:
        def __init__(self, server, token, *, timeout):
            assert (server, token, timeout) == ("https://mesh.example.com", "runner-token", 5.0)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    class Service:
        def __init__(self, _client, *, capabilities):
            assert capabilities.protocol_version == "runner-v1"

        def run_once(self):
            return True

    monkeypatch.setattr(cli, "RunnerControlPlaneClient", Client)
    monkeypatch.setattr(cli, "LocalRunnerService", Service)

    result = cli.runner_start(argparse.Namespace(server=None, interval=20.0, timeout=5.0, once=True))

    assert result == 0
    assert '"status": "processed"' in capsys.readouterr().out

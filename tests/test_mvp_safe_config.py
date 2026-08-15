from __future__ import annotations

import logging

import pytest
from fastapi import HTTPException, Response

import agentmesh.embedding as embedding
from agentmesh.app import initialize_application_data
from agentmesh.auth import verify_password
from agentmesh.embedding import EmbeddingConfig
from agentmesh.models import LoginRequest
from agentmesh.routes import auth as auth_routes
from agentmesh.seed import PROJECT, WORKSPACE
from agentmesh.store import SQLiteStore


def test_embedding_is_disabled_without_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENTMESH_EMBEDDING_ENABLED", raising=False)
    monkeypatch.delenv("AGENTMESH_EMBEDDING_API_URL", raising=False)
    monkeypatch.delenv("AGENTMESH_EMBEDDING_API_KEY", raising=False)

    config = EmbeddingConfig.from_env()

    assert config.enabled is False
    assert config.api_url is None
    assert config.api_key is None


@pytest.mark.parametrize("missing_name", ["AGENTMESH_EMBEDDING_API_URL", "AGENTMESH_EMBEDDING_API_KEY"])
def test_enabled_embedding_requires_url_and_key(
    monkeypatch: pytest.MonkeyPatch,
    missing_name: str,
) -> None:
    monkeypatch.setenv("AGENTMESH_EMBEDDING_ENABLED", "true")
    monkeypatch.setenv("AGENTMESH_EMBEDDING_API_URL", "https://embedding.example.test/v1")
    monkeypatch.setenv("AGENTMESH_EMBEDDING_API_KEY", "test-only-key")
    monkeypatch.delenv(missing_name, raising=False)

    with pytest.raises(ValueError, match="Embedding requires API URL and API key"):
        EmbeddingConfig.from_env()


def test_embedding_failure_does_not_log_url_or_key(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    api_url = "https://embedding.example.test/private"
    api_key = "test-only-key"

    class FailingClient:
        def post(self, *_args, **_kwargs):
            raise RuntimeError(f"request failed for {api_url} with {api_key}")

    monkeypatch.setattr(embedding, "EMBEDDING_ENABLED", True)
    monkeypatch.setattr(embedding, "EMBEDDING_API_URL", api_url)
    monkeypatch.setattr(embedding, "EMBEDDING_API_KEY", api_key)
    monkeypatch.setattr(embedding, "_get_client", lambda: FailingClient())

    with caplog.at_level(logging.WARNING, logger="agentmesh.embedding"):
        assert embedding.embed_text("safe input") is None

    assert api_url not in caplog.text
    assert api_key not in caplog.text


def test_default_application_initialization_does_not_seed_demo_admin(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGENTMESH_DEMO_MODE", raising=False)
    repository = SQLiteStore(db_path=tmp_path / "production.sqlite3")

    initialize_application_data(repository)
    assert repository.get_workspace(WORKSPACE.id) is not None
    assert repository.get_project(PROJECT.id) is not None

    assert repository.get_user("usr_admin") is None
    assert repository.get_auth_credential("usr_admin") is None


def test_explicit_demo_mode_seeds_demo_admin(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTMESH_DEMO_MODE", "1")
    repository = SQLiteStore(db_path=tmp_path / "demo.sqlite3")

    initialize_application_data(repository)

    credential = repository.get_auth_credential("usr_admin")
    assert repository.get_user("usr_admin") is not None
    assert credential is not None
    assert verify_password("admin123", credential.password_hash)


def test_default_login_does_not_recreate_demo_credentials(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGENTMESH_DEMO_MODE", raising=False)
    repository = SQLiteStore(db_path=tmp_path / "login.sqlite3")
    monkeypatch.setattr(auth_routes, "store", repository)

    with pytest.raises(HTTPException) as exc_info:
        auth_routes.login(LoginRequest(user_id="usr_admin", password="admin123"), Response())

    assert exc_info.value.status_code == 401
    assert repository.get_auth_credential("usr_admin") is None

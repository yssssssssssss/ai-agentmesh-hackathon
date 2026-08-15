from __future__ import annotations

from tests.test_chat_flow import authenticated_client


def test_market_status_reports_worker_state_and_counts() -> None:
    client = authenticated_client()

    response = client.get("/api/market/status")

    assert response.status_code == 200
    payload = response.json()
    assert "enabled" in payload
    assert "publish_worker" in payload and "running" in payload["publish_worker"]
    assert "scout_worker" in payload and "running" in payload["scout_worker"]
    assert "counts" in payload
    for key in ("signals", "matches", "consent_grants", "participants"):
        assert key in payload["counts"]


def test_market_board_returns_signals_and_matches() -> None:
    client = authenticated_client()

    response = client.get("/api/market/board")

    assert response.status_code == 200
    payload = response.json()
    for key in ("enabled", "publish_worker", "scout_worker", "counts", "signals", "matches"):
        assert key in payload
    assert isinstance(payload["signals"], list)
    assert isinstance(payload["matches"], list)


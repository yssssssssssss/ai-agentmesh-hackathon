from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import agentmesh.app as app_module
from agentmesh.app import app

client = TestClient(app)


def test_root_and_explicit_product_routes_serve_react_index(monkeypatch, tmp_path: Path) -> None:
    index = tmp_path / "index.html"
    index.write_text('<div id="root">react-shell</div>', encoding="utf-8")
    monkeypatch.setattr(app_module, "FRONTEND_INDEX", index)

    for path in (
        "/",
        "/digital-self",
        "/workspace/thread/example",
        "/digital-human/profile",
        "/insights",
        "/knowledge/item/example",
        "/collaboration",
        "/tasks/task/example",
        "/admin/users",
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert "react-shell" in response.text


def test_product_route_returns_503_when_react_build_is_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(app_module, "FRONTEND_INDEX", tmp_path / "missing-index.html")

    response = client.get("/workspace")

    assert response.status_code == 503
    assert response.json() == {"detail": "React frontend is not built"}


def test_legacy_route_serves_old_application() -> None:
    response = client.get("/legacy/app.html")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert response.text == (app_module.ROOT_DIR / "app.html").read_text(encoding="utf-8")


def test_built_asset_is_served_with_static_content_type() -> None:
    assets = sorted(path for path in app_module.FRONTEND_ASSETS.iterdir() if path.is_file())
    assert assets, "The checked-in React build must contain at least one asset"

    response = client.get(f"/assets/{assets[0].name}")

    assert response.status_code == 200
    assert response.headers["content-type"] != "text/html; charset=utf-8"


def test_unknown_api_route_stays_a_json_404() -> None:
    response = client.get("/api/does-not-exist")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": "Not Found"}


def test_unknown_non_product_route_is_not_rewritten_to_react() -> None:
    response = client.get("/not-a-product-route")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")

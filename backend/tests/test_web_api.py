"""W1 web adapter tests: health, anonymous sessions, projects, error contract.

These tests need the ``web`` optional dependency group; they skip cleanly in a
core-only environment (the deterministic core never depends on the adapter).
"""

from __future__ import annotations

from datetime import timedelta

import pytest

# Guard every optional web dependency, so a partial core-only environment
# (e.g. fastapi present but sqlalchemy absent) skips instead of failing.
pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")
pytest.importorskip("httpx")  # fastapi.testclient needs it

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from saudi_plot_api.config import Settings  # noqa: E402
from saudi_plot_api.database import Base, utcnow  # noqa: E402
from saudi_plot_api.main import create_app  # noqa: E402
from saudi_plot_api.models import AnonymousSession  # noqa: E402


def make_settings(**overrides) -> Settings:
    values = {
        "environment": "test",
        "database_url": "sqlite://",  # in-memory, StaticPool-shared
        "cookie_secure": False,  # local/test override; TestClient speaks http
        "cors_origins": [],
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def app():
    application = create_app(make_settings())
    Base.metadata.create_all(application.state.engine)
    return application


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


def fresh_client(app) -> TestClient:
    """A second client with its own cookie jar (a different browser)."""
    return TestClient(app)


def create_session(client: TestClient) -> dict:
    response = client.post("/api/v1/sessions")
    assert response.status_code == 201
    return response.json()


# ── Health ──────────────────────────────────────────────────────────────────


def test_health_live(client):
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "live"}


def test_health_ready_checks_database(client, app):
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}

    app.state.engine.dispose()
    app.state.engine = _BrokenEngine()
    broken = client.get("/health/ready")
    assert broken.status_code == 503
    body = broken.json()
    assert body["error"]["code"] == "database_unavailable"


class _BrokenEngine:
    def connect(self):
        raise RuntimeError("simulated outage")

    def dispose(self):
        pass


# ── Sessions ────────────────────────────────────────────────────────────────


def test_create_session_sets_hardened_cookie_and_stores_only_hash(client, app):
    body = create_session(client)
    assert body["status"] == "active"

    set_cookie = client.cookies.get("spd_session")
    assert set_cookie  # the raw token lives in the cookie...
    with app.state.session_factory() as db:
        stored = db.execute(select(AnonymousSession)).scalars().all()
        assert len(stored) == 1
        assert stored[0].token_hash != set_cookie  # ...never in the database
        assert len(stored[0].token_hash) == 64  # sha256 hex

    # Cookie hardening attributes on the raw header.
    raw = client.post("/api/v1/sessions").headers["set-cookie"]
    assert "HttpOnly" in raw
    assert "SameSite=lax" in raw
    assert "Path=/" in raw
    assert "Secure" not in raw  # explicit local-development override


def test_secure_cookie_flag_follows_settings():
    application = create_app(make_settings(cookie_secure=True))
    Base.metadata.create_all(application.state.engine)
    with TestClient(application) as secure_client:
        raw = secure_client.post("/api/v1/sessions").headers["set-cookie"]
    assert "Secure" in raw


def test_read_current_session(client):
    created = create_session(client)
    response = client.get("/api/v1/sessions/current")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == created["id"]
    assert "token" not in body and "token_hash" not in body


def test_current_session_requires_cookie(client):
    response = client.get("/api/v1/sessions/current")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "session_required"


def test_garbage_cookie_is_invalid(client):
    client.cookies.set("spd_session", "not-a-real-token")
    response = client.get("/api/v1/sessions/current")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "session_invalid"


def test_session_expiration(client, app):
    created = create_session(client)
    with app.state.session_factory() as db:
        row = db.get(AnonymousSession, created["id"])
        row.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()

    response = client.get("/api/v1/sessions/current")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "session_expired"

    # The expiry is recorded, and the session stays unusable.
    with app.state.session_factory() as db:
        assert db.get(AnonymousSession, created["id"]).status == "expired"
    assert client.get("/api/v1/sessions/current").status_code == 401


def test_session_last_seen_updates(client, app):
    created = create_session(client)
    with app.state.session_factory() as db:
        row = db.get(AnonymousSession, created["id"])
        row.last_seen_at = utcnow() - timedelta(hours=2)
        db.commit()

    client.get("/api/v1/sessions/current")
    with app.state.session_factory() as db:
        refreshed = db.get(AnonymousSession, created["id"])
        assert utcnow() - refreshed.last_seen_at < timedelta(minutes=1)


# ── Projects ────────────────────────────────────────────────────────────────


def test_create_project(client):
    create_session(client)
    response = client.post("/api/v1/projects", json={"current_step": "upload"})
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "draft"
    assert body["current_step"] == "upload"
    assert body["schema_version"] == 1


def test_read_project(client):
    create_session(client)
    created = client.post("/api/v1/projects", json={}).json()
    response = client.get(f"/api/v1/projects/{created['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_patch_project(client):
    create_session(client)
    created = client.post("/api/v1/projects", json={}).json()
    response = client.patch(
        f"/api/v1/projects/{created['id']}",
        json={"status": "in_progress", "current_step": "questions/3"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "in_progress"
    assert body["current_step"] == "questions/3"
    assert body["updated_at"] >= created["updated_at"]


def test_projects_require_session(client):
    assert client.post("/api/v1/projects", json={}).status_code == 401
    assert client.get("/api/v1/projects/anything").status_code == 401


def test_cross_session_isolation_returns_404(client, app):
    create_session(client)
    project = client.post("/api/v1/projects", json={}).json()

    other = fresh_client(app)
    create_session(other)
    for response in (
        other.get(f"/api/v1/projects/{project['id']}"),
        other.patch(f"/api/v1/projects/{project['id']}", json={"status": "completed"}),
    ):
        assert response.status_code == 404  # existence is not leaked
        assert response.json()["error"]["code"] == "project_not_found"

    # The owner still sees it, unchanged.
    unchanged = client.get(f"/api/v1/projects/{project['id']}")
    assert unchanged.status_code == 200
    assert unchanged.json()["status"] == "draft"


def test_missing_project_is_404(client):
    create_session(client)
    response = client.get("/api/v1/projects/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "project_not_found"


# ── Error contract ──────────────────────────────────────────────────────────


def test_invalid_payload_shape(client):
    create_session(client)
    response = client.post("/api/v1/projects", json={"current_step": "made-up-page"})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "invalid_payload"
    assert body["error"]["details"]["fields"][0]["loc"][-1] == "current_step"
    # The submitted value is not echoed back.
    assert "made-up-page" not in str(body["error"]["details"])


def test_unknown_field_rejected(client):
    create_session(client)
    response = client.post("/api/v1/projects", json={"deed_number": "123"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_payload"


def test_stable_error_shape_everywhere(client):
    for response in (
        client.get("/api/v1/sessions/current"),  # 401 ApiError
        client.get("/no/such/route"),  # 404 starlette HTTPException
        client.post("/api/v1/projects", json={"status": 3}),  # 401 (no session) or 422
    ):
        body = response.json()
        assert set(body) == {"error", "request_id"}
        assert set(body["error"]) == {"code", "message", "details"}
        assert isinstance(body["error"]["code"], str)
        assert response.headers["x-request-id"] == body["request_id"]
        text = str(body)
        assert "Traceback" not in text
        assert "sqlite" not in text.lower()


# ── Configuration guards ────────────────────────────────────────────────────


def test_wildcard_cors_with_credentials_is_refused():
    with pytest.raises(Exception, match="explicit origins"):
        make_settings(cors_origins=["*"])


def test_production_requires_secure_cookies():
    with pytest.raises(Exception, match="local-development override"):
        make_settings(environment="production", cookie_secure=False)


def test_cors_allows_only_configured_origin():
    application = create_app(make_settings(cors_origins=["http://localhost:5173"]))
    Base.metadata.create_all(application.state.engine)
    with TestClient(application) as cors_client:
        allowed = cors_client.get("/health/live", headers={"Origin": "http://localhost:5173"})
        assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
        assert allowed.headers["access-control-allow-credentials"] == "true"
        denied = cors_client.get("/health/live", headers={"Origin": "http://evil.example"})
        assert "access-control-allow-origin" not in denied.headers


# ── Codex round 1 regressions ───────────────────────────────────────────────


def test_patch_explicit_null_clears_current_step(client):
    """Explicit null is an answer, not an omission (ADR-WEB-001 rule 4)."""
    create_session(client)
    created = client.post("/api/v1/projects", json={"current_step": "upload"}).json()

    untouched = client.patch(f"/api/v1/projects/{created['id']}", json={"status": "in_progress"})
    assert untouched.json()["current_step"] == "upload"  # omitted field stays

    cleared = client.patch(f"/api/v1/projects/{created['id']}", json={"current_step": None})
    assert cleared.status_code == 200
    assert cleared.json()["current_step"] is None


def test_patch_explicit_null_status_rejected(client):
    create_session(client)
    created = client.post("/api/v1/projects", json={}).json()
    response = client.patch(f"/api/v1/projects/{created['id']}", json={"status": None})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_payload"


def test_cors_preflight_rejection_uses_error_envelope():
    application = create_app(make_settings(cors_origins=["http://localhost:5173"]))
    Base.metadata.create_all(application.state.engine)
    with TestClient(application) as cors_client:
        ok = cors_client.options(
            "/api/v1/sessions",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert ok.status_code == 200
        assert "x-request-id" in ok.headers

        rejected = cors_client.options(
            "/api/v1/sessions",
            headers={
                "Origin": "http://evil.example",
                "Access-Control-Request-Method": "DELETE",
            },
        )
        assert rejected.status_code == 400
        body = rejected.json()
        assert body["error"]["code"] == "cors_rejected"
        assert rejected.headers["x-request-id"] == body["request_id"]


def test_driver_qualified_sqlite_url_creates_parent_directory(tmp_path):
    from saudi_plot_api.database import create_database_engine

    db_file = tmp_path / "nested" / "deeper" / "app.db"
    engine = create_database_engine(f"sqlite+pysqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(engine)
    assert db_file.exists()
    engine.dispose()


# ── Codex round 2 regressions ───────────────────────────────────────────────


def test_unexpected_error_gets_envelope_request_id_and_cors():
    """An unhandled exception must still produce the envelope AND flow out
    through CORS + request-id middleware (Starlette's ServerErrorMiddleware
    sits outside both and must never answer first)."""
    application = create_app(make_settings(cors_origins=["http://localhost:5173"]))
    Base.metadata.create_all(application.state.engine)

    @application.get("/boom")
    def boom():
        raise RuntimeError("secret internal detail")

    with TestClient(application) as boom_client:
        response = boom_client.get("/boom", headers={"Origin": "http://localhost:5173"})
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert response.headers["x-request-id"] == body["request_id"]
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "secret internal detail" not in response.text


# ── Codex round 3 regressions ───────────────────────────────────────────────


def test_samesite_none_requires_secure_cookies():
    with pytest.raises(Exception, match="requires cookie_secure=true"):
        make_settings(cookie_samesite="none", cookie_secure=False)
    assert make_settings(cookie_samesite="none", cookie_secure=True).cookie_samesite == "none"


def test_sqlite_enforces_project_session_foreign_key(app):
    """projects.session_id must be a real constraint, not documentation."""
    from sqlalchemy.exc import IntegrityError

    from saudi_plot_api.models import Project

    with app.state.session_factory() as db:
        db.add(Project(session_id="no-such-session"))
        with pytest.raises(IntegrityError):
            db.commit()


# ── Codex round 4 regressions ───────────────────────────────────────────────


def test_cross_site_session_creation_is_rejected(client):
    """A cross-site form POST must not replace the session cookie (login
    CSRF): the cookie is the only credential for the victim's projects."""
    response = client.post("/api/v1/sessions", headers={"Origin": "http://evil.example"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "origin_not_allowed"
    assert "set-cookie" not in response.headers

    via_referer = client.post(
        "/api/v1/sessions", headers={"Referer": "http://evil.example/attack.html"}
    )
    assert via_referer.status_code == 403


def test_trusted_origins_may_create_sessions_and_projects(app):
    application = create_app(make_settings(cors_origins=["http://localhost:5173"]))
    Base.metadata.create_all(application.state.engine)
    with TestClient(application) as trusted:
        frontend = {"Origin": "http://localhost:5173"}
        assert trusted.post("/api/v1/sessions", headers=frontend).status_code == 201
        assert trusted.post("/api/v1/projects", json={}, headers=frontend).status_code == 201
        # Same-origin (the API itself) also passes.
        assert (
            trusted.post("/api/v1/sessions", headers={"Origin": "http://testserver"}).status_code
            == 201
        )


def test_cross_site_project_mutations_are_rejected(client):
    create_session(client)
    created = client.post("/api/v1/projects", json={}).json()
    evil = {"Origin": "http://evil.example"}
    assert client.post("/api/v1/projects", json={}, headers=evil).status_code == 403
    patched = client.patch(
        f"/api/v1/projects/{created['id']}", json={"status": "completed"}, headers=evil
    )
    assert patched.status_code == 403
    assert client.get(f"/api/v1/projects/{created['id']}").json()["status"] == "draft"

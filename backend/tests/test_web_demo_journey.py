"""W2 demo-journey tests: documents, plot, brief, program, geo, runs, share.

Uses the real deterministic engine for the complete-run test (module-scoped,
executed once) and mocks only the external Gemini provider.
"""

from __future__ import annotations

import io
import json
import sqlite3
import time
from datetime import timedelta

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic_settings")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from saudi_plot_api.config import Settings  # noqa: E402
from saudi_plot_api.database import Base, utcnow  # noqa: E402
from saudi_plot_api.main import create_app  # noqa: E402
from saudi_plot_api.models import PricingConfiguration, ShareToken  # noqa: E402
from saudi_plot_api.services import gemini, storage  # noqa: E402
from saudi_plot_api.services.geo_knowledge import resolve_character  # noqa: E402

# 1x1 transparent PNG.
PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63fcffffff3f0005fe02fea72d224a0000000049454e44ae426082"
)

TERMINAL = ("completed", "completed_with_assumptions", "unsupported_requirements", "failed")


def make_settings(tmp_path, **overrides) -> Settings:
    values = {
        "environment": "test",
        "database_url": "sqlite://",
        "cookie_secure": False,
        "storage_root": tmp_path / "storage",
        # Explicitly suppress any GEMINI_API_KEY present in the process
        # environment so tests that expect "no key configured" are not
        # accidentally satisfied by a real key injected by the host.
        # Individual tests that want a key pass gemini_api_key="test-key".
        "gemini_api_key": "",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def build_app(settings: Settings):
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    with app.state.session_factory() as db:
        db.add(PricingConfiguration(active=True, label="demo_concept_package", amount=18000.0))
        db.commit()
    return app


def start_client(app) -> TestClient:
    client = TestClient(app)
    assert client.post("/api/v1/sessions").status_code == 201
    return client


def create_project(client: TestClient) -> str:
    return client.post("/api/v1/projects", json={}).json()["id"]


REFERENCE_PLOT = {
    "width_m": 20,
    "height_m": 30,
    "latitude": 26.42,
    "longitude": 50.10,
    "boundaries": {
        "north": "20 م — على شارع عرض 15 م",
        "south": "20 م",
        "east": "30 م",
        "west": "30 م",
    },
    "source": "manual",
}


# ── Documents: upload safety ────────────────────────────────────────────────


def test_upload_stores_file_with_hash_and_reports_unconfigured_extraction(tmp_path):
    app = build_app(make_settings(tmp_path))
    with start_client(app) as client:
        pid = create_project(client)
        response = client.post(
            f"/api/v1/projects/{pid}/documents",
            files={"file": ("my deed.png", io.BytesIO(PNG_BYTES), "image/png")},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "extraction_failed"
        assert body["error_code"] == "extraction_unconfigured"  # no GEMINI_API_KEY

        document_id = body["document_id"]
        doc = client.get(f"/api/v1/documents/{document_id}").json()
        assert doc["size_bytes"] == len(PNG_BYTES)
        assert len(doc["sha256"]) == 64
        # Server-generated name: the user filename never becomes a path.
        stored = list((tmp_path / "storage").rglob("*.png"))
        assert len(stored) == 1
        assert "my deed" not in stored[0].name


def test_upload_rejects_bad_mime_and_oversize(tmp_path):
    app = build_app(make_settings(tmp_path, upload_max_bytes=100))
    with start_client(app) as client:
        pid = create_project(client)
        bad_mime = client.post(
            f"/api/v1/projects/{pid}/documents",
            files={"file": ("x.exe", io.BytesIO(b"MZ..."), "application/x-msdownload")},
        )
        assert bad_mime.status_code == 415
        assert bad_mime.json()["error"]["code"] == "unsupported_file_type"

        too_big = client.post(
            f"/api/v1/projects/{pid}/documents",
            files={"file": ("big.png", io.BytesIO(b"a" * 200), "image/png")},
        )
        assert too_big.status_code == 413
        assert too_big.json()["error"]["code"] == "file_too_large"


def test_mocked_gemini_extraction_success(tmp_path, monkeypatch):
    extraction = {
        "is_valid_deed": True,
        "property": {"area_m2": 600.0, "city": "الدمام"},
        "boundaries": {"north": "20 م — على شارع عرض 15 م"},
        "field_confidence": {"area_m2": 0.9},
    }
    payload = {"candidates": [{"content": {"parts": [{"text": json.dumps(extraction)}]}}]}
    monkeypatch.setattr(gemini, "_post_generate", lambda *args, **kwargs: payload)
    app = build_app(make_settings(tmp_path, gemini_api_key="test-key"))
    with start_client(app) as client:
        pid = create_project(client)
        response = client.post(
            f"/api/v1/projects/{pid}/documents",
            files={"file": ("deed.png", io.BytesIO(PNG_BYTES), "image/png")},
        )
        body = response.json()
        assert body["status"] == "extracted"
        assert body["extraction"]["property"]["city"] == "الدمام"
        assert body["extraction"]["field_confidence"]["area_m2"] == 0.9

        stored = client.get(f"/api/v1/documents/{body['document_id']}/extraction").json()
        assert stored["extraction"]["is_valid_deed"] is True


def test_storage_path_traversal_is_refused(tmp_path):
    root = tmp_path / "root"
    for hostile in ("../escape.txt", "..\\escape.txt", "C:evil.txt", "/abs/path.txt", "a/../../b"):
        with pytest.raises(storage.StorageError):
            storage.resolve_relative(root, hostile)
    # Sanity: a legitimate nested path resolves inside the root.
    ok = storage.resolve_relative(root, "projects/p1/documents/x.png")
    assert ok.is_relative_to(root.resolve())


# ── Plot / brief / room program persistence ─────────────────────────────────


def test_plot_brief_and_program_persist_and_validate(tmp_path):
    app = build_app(make_settings(tmp_path))
    with start_client(app) as client:
        pid = create_project(client)
        put = client.put(f"/api/v1/projects/{pid}/plot", json=REFERENCE_PLOT)
        assert put.status_code == 200
        got = client.get(f"/api/v1/projects/{pid}/plot").json()
        assert got["width_m"] == 20 and got["boundaries"]["north"].startswith("20")

        brief = client.put(
            f"/api/v1/projects/{pid}/design-brief",
            json={"answers": {"ui_answers": {"kitchenType": "مغلق"}}},
        )
        assert brief.status_code == 200
        assert (
            client.get(f"/api/v1/projects/{pid}/design-brief").json()["answers"]["ui_answers"][
                "kitchenType"
            ]
            == "مغلق"
        )

        program = client.put(
            f"/api/v1/projects/{pid}/room-program",
            json={"counts": {"master": 1, "bedroom": 3, "bathroom": 2, "living": 1}},
        )
        assert program.status_code == 200
        assert program.json()["validation"]["valid"] is True

        invalid = client.post(
            f"/api/v1/projects/{pid}/room-program/validate",
            json={"counts": {"master": 0, "living": 0}},
        )
        body = invalid.json()
        assert body["valid"] is False and len(body["issues"]) >= 2
        assert "Compact 3BR" in body["engine_note"]  # honest limitation statement

        unknown_room = client.put(
            f"/api/v1/projects/{pid}/room-program", json={"counts": {"pool": 1}}
        )
        assert unknown_room.status_code == 422


def test_plot_rejects_half_coordinate_pair(tmp_path):
    """A latitude without a longitude (or vice versa) must be rejected at the
    boundary -- it would otherwise mix with defaults into a fabricated
    location."""
    app = build_app(make_settings(tmp_path))
    with start_client(app) as client:
        pid = create_project(client)
        for dropped in ("latitude", "longitude"):
            half = {k: v for k, v in REFERENCE_PLOT.items() if k != dropped}
            response = client.put(f"/api/v1/projects/{pid}/plot", json=half)
            assert response.status_code == 422, dropped


# ── Geo knowledge ───────────────────────────────────────────────────────────


def _fixture_geo_db(tmp_path):
    db_path = tmp_path / "geo.sqlite"
    con = sqlite3.connect(db_path)
    con.executescript(
        """
        CREATE TABLE zones (zone_id TEXT, name_ar TEXT, name_en TEXT, zone_code TEXT,
            zone_type TEXT, allowed_styles TEXT, map_id TEXT, geometry_geojson TEXT,
            geometry_confidence REAL, boundary_accuracy_meters REAL, review_status TEXT,
            bbox_minx REAL, bbox_miny REAL, bbox_maxx REAL, bbox_maxy REAL);
        CREATE TABLE rules (rule_id TEXT, title_en TEXT, title_ar TEXT, category TEXT,
            original_text_en TEXT, rule_type TEXT, applicable_styles TEXT,
            extraction_confidence REAL, review_status TEXT);
        CREATE TABLE rule_zone_links (rule_id TEXT, zone_id TEXT, relationship_type TEXT,
            priority INTEGER, review_status TEXT);
        CREATE TABLE conflicts (conflict_id TEXT, zone_ids TEXT, conflict_type TEXT,
            review_status TEXT, winning_zone_id TEXT, description TEXT);
        """
    )
    square = {
        "type": "Polygon",
        "coordinates": [[[50.0, 26.0], [50.2, 26.0], [50.2, 26.2], [50.0, 26.2], [50.0, 26.0]]],
    }
    far_square = {
        "type": "Polygon",
        "coordinates": [[[51.0, 27.0], [51.2, 27.0], [51.2, 27.2], [51.0, 27.2], [51.0, 27.0]]],
    }
    con.execute(
        "INSERT INTO zones VALUES ('Z1','تقليدي','Level 1','level_1','style',"
        "'[\"traditional\"]','MAP-DMA-02',?,0.4,3000,'approved',50.0,26.0,50.2,26.2)",
        (json.dumps(square),),
    )
    # Overlapping approved zone containing the same point (for conflicts).
    con.execute(
        "INSERT INTO zones VALUES ('Z1B','انتقالي','Level 2','level_2','style',"
        "'[\"traditional\",\"transitional\"]','MAP-DMA-01',?,0.3,3000,'approved',"
        "50.0,26.0,50.2,26.2)",
        (json.dumps(square),),
    )
    # Pending-review zone containing the point: visible, but never guidance.
    con.execute(
        "INSERT INTO zones VALUES ('Z3','معلق','Pending zone','level_2','style',"
        "'[\"traditional\"]','MAP-DMA-02',?,0.4,3000,'pending_review',50.0,26.0,50.2,26.2)",
        (json.dumps(square),),
    )
    # Zone far from the test point (for the irrelevant-conflict case).
    con.execute(
        "INSERT INTO zones VALUES ('Z2','بعيد','Far zone','level_1','style',"
        "'[\"traditional\"]','MAP-DMA-02',?,0.4,3000,'approved',51.0,27.0,51.2,27.2)",
        (json.dumps(far_square),),
    )
    con.execute(
        "INSERT INTO rules VALUES ('R1','Facade','واجهة','facade','Use traditional openings',"
        "'guidance','[\"traditional\"]',0.8,'approved')"
    )
    con.execute(
        "INSERT INTO rules VALUES ('R2','Pending','معلق','facade','Pending rule',"
        "'guidance','[]',0.5,'pending_review')"
    )
    con.execute(
        "INSERT INTO rules VALUES ('R3','Linked pending','رابط معلق','facade',"
        "'Approved rule behind a pending link','guidance','[]',0.9,'approved')"
    )
    con.execute("INSERT INTO rule_zone_links VALUES ('R1','Z1','applies_to',2,'approved')")
    con.execute("INSERT INTO rule_zone_links VALUES ('R2','Z1','applies_to',1,'approved')")
    con.execute("INSERT INTO rule_zone_links VALUES ('R3','Z1','applies_to',3,'pending_review')")
    con.execute("INSERT INTO rule_zone_links VALUES ('R1','Z3','applies_to',1,'approved')")
    # Conflict between two zones that BOTH contain the point -> relevant.
    con.execute(
        "INSERT INTO conflicts VALUES ('C1','[\"Z1\",\"Z1B\"]','overlap','open',NULL,'overlap')"
    )
    # Conflict with a zone the point is NOT inside -> irrelevant here.
    con.execute(
        "INSERT INTO conflicts VALUES ('C2','[\"Z1\",\"Z2\"]','overlap','open',NULL,'far overlap')"
    )
    con.commit()
    con.close()
    return db_path


def test_geo_lookup_finds_zone_and_hides_unapproved_guidance(tmp_path):
    db_path = _fixture_geo_db(tmp_path)
    result = resolve_character(db_path, 26.1, 50.1)
    assert result.available is True
    # City-map zones (MAP-DMA-02) sort ahead of the metropolitan map's Z1B.
    assert [z["zone_id"] for z in result.candidate_zones] == ["Z1", "Z3", "Z1B"]
    assert result.recommended_character == "traditional"
    # Only the fully approved chain survives: R2's rule is pending, R3's zone
    # link is pending, and pending zone Z3 never contributes guidance.
    assert [g["rule_id"] for g in result.applicable_guidance] == ["R1"]
    assert result.requires_confirmation is True
    assert any("approximate" in w for w in result.warnings)  # no legal claim
    assert any("Z3" in w and "pending" in w for w in result.warnings)

    outside = resolve_character(db_path, 10.0, 10.0)
    assert outside.candidate_zones == [] and outside.recommended_character is None


def test_geo_conflicts_require_point_inside_every_conflicting_zone(tmp_path):
    db_path = _fixture_geo_db(tmp_path)
    result = resolve_character(db_path, 26.1, 50.1)
    # C1 overlaps Z1 and Z1B, both containing the point -> reported. C2
    # involves the far zone Z2 the point is not inside -> irrelevant here.
    assert [c["conflict_id"] for c in result.conflicts] == ["C1"]
    assert any("conflict" in w for w in result.warnings)


def test_geo_lookup_unconfigured_is_explicit(tmp_path):
    result = resolve_character(None, 26.1, 50.1)
    assert result.available is False
    assert result.requires_confirmation is True


def test_resolve_character_endpoint_requires_coordinates(tmp_path):
    app = build_app(make_settings(tmp_path))
    with start_client(app) as client:
        pid = create_project(client)
        no_plot = client.post(f"/api/v1/projects/{pid}/resolve-character")
        assert no_plot.status_code == 422
        assert no_plot.json()["error"]["code"] == "coordinates_required"


# ── The complete design run (real engine, module-scoped) ────────────────────


@pytest.fixture(scope="module")
def completed_run(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("demo-run")
    settings = make_settings(tmp_path, geo_knowledge_db=None)
    app = build_app(settings)
    client = start_client(app)
    pid = create_project(client)
    client.put(f"/api/v1/projects/{pid}/plot", json=dict(REFERENCE_PLOT, width_m=70, height_m=42))
    client.put(
        f"/api/v1/projects/{pid}/design-brief",
        json={"answers": {"ui_answers": {"kitchenType": "مغلق", "hasElderly": True}}},
    )
    client.put(
        f"/api/v1/projects/{pid}/room-program",
        json={"counts": {"master": 1, "bedroom": 3, "bathroom": 2, "living": 1}},
    )
    started = client.post(f"/api/v1/projects/{pid}/design-runs", json={})
    assert started.status_code == 202  # returns quickly with the run id
    run_id = started.json()["id"]
    deadline = time.time() + 300
    while time.time() < deadline:
        run = client.get(f"/api/v1/design-runs/{run_id}").json()
        if run["status"] in TERMINAL:
            break
        time.sleep(0.5)
    yield {"app": app, "client": client, "project_id": pid, "run_id": run_id, "run": run}
    client.close()


def test_run_completes_with_honest_assumptions(completed_run):
    run = completed_run["run"]
    assert run["status"] == "completed_with_assumptions"
    assert run["support_status"] == "supported_with_assumptions"
    statuses = [event["status"] for event in run["events"]]
    assert statuses[:7] == [
        "preparing_inputs",
        "extracting_deed",
        "resolving_character",
        "validating_requirements",
        "generating_candidates",
        "evaluating_candidates",
        "preparing_outputs",
    ]
    assert "generating_presentation_render" in statuses
    assert run["design_fingerprint"] and len(run["design_fingerprint"]) == 64


def test_run_result_reports_files_and_unapplied_answers(completed_run):
    client = completed_run["client"]
    result = client.get(f"/api/v1/design-runs/{completed_run['run_id']}/result").json()
    kinds = {f["kind"] for f in result["files"]}
    assert {"pdf", "dxf", "svg_plan", "svg_elevation", "run_json"} <= kinds
    # The non-reference plot is an explicit assumption, never silent.
    assert any("20 m x 30 m" in a for a in result["assumptions"])
    unapplied = {u["answer"] for u in result["unapplied_answers"]}
    assert "room_catalog" in unapplied and "ui_answers" in unapplied


def test_output_download_and_authorization(completed_run):
    client = completed_run["client"]
    run_id = completed_run["run_id"]
    result = client.get(f"/api/v1/design-runs/{run_id}/result").json()
    svg = next(f for f in result["files"] if f["kind"] == "svg_plan")
    download = client.get(f"/api/v1/design-runs/{run_id}/files/{svg['id']}")
    assert download.status_code == 200
    assert b"<svg" in download.content[:200]

    intruder = TestClient(completed_run["app"])
    intruder.post("/api/v1/sessions")
    assert intruder.get(f"/api/v1/design-runs/{run_id}").status_code == 404
    assert intruder.get(f"/api/v1/design-runs/{run_id}/files/{svg['id']}").status_code == 404
    assert intruder.get(f"/api/v1/projects/{completed_run['project_id']}/plot").status_code == 404
    intruder.close()


def test_dwg_endpoint_is_honest_about_missing_converter(completed_run):
    from saudi_plot_api.services import dwg as dwg_service

    if dwg_service.find_converter() is not None:
        pytest.skip("a real DWG converter is installed on this machine")
    client = completed_run["client"]
    response = client.get(f"/api/v1/design-runs/{completed_run['run_id']}/dwg")
    assert response.status_code == 501
    body = response.json()["error"]
    assert body["code"] == "dwg_converter_unavailable"
    assert "ODA File Converter" in body["details"]["required_dependency"]


def test_mocked_presentation_render(completed_run, monkeypatch):
    import base64

    payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "inlineData": {
                                "mimeType": "image/png",
                                "data": base64.b64encode(PNG_BYTES).decode(),
                            }
                        }
                    ]
                }
            }
        ]
    }
    monkeypatch.setattr(gemini, "_post_generate", lambda *args, **kwargs: payload)
    settings = completed_run["app"].state.settings
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    client = completed_run["client"]
    run_id = completed_run["run_id"]

    created = client.post(f"/api/v1/design-runs/{run_id}/presentation-render")
    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "completed"
    assert body["design_fingerprint"] == completed_run["run"]["design_fingerprint"]

    image = client.get(f"/api/v1/design-runs/{run_id}/presentation-render/image")
    assert image.status_code == 200
    assert image.content == PNG_BYTES


def test_result_page_surfaces_presentation_render_url(completed_run, monkeypatch):
    """After a successful render the /result endpoint must include its URL.

    This exercises the full path: mocked Gemini returns a real PNG ->
    attempt_presentation_render stores it -> read_result queries the
    completed render row -> presentation_render_url is non-null and the
    URL actually serves the stored bytes.
    """
    import base64

    payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "inlineData": {
                                "mimeType": "image/png",
                                "data": base64.b64encode(PNG_BYTES).decode(),
                            }
                        }
                    ]
                }
            }
        ]
    }
    monkeypatch.setattr(gemini, "_post_generate", lambda *args, **kwargs: payload)
    settings = completed_run["app"].state.settings
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    client = completed_run["client"]
    run_id = completed_run["run_id"]

    # Trigger (or re-trigger) the render so a completed row definitely exists.
    created = client.post(f"/api/v1/design-runs/{run_id}/presentation-render")
    assert created.status_code == 200
    assert created.json()["status"] == "completed"

    # The result page must now expose the render URL.
    result = client.get(f"/api/v1/design-runs/{run_id}/result").json()
    render_url = result.get("presentation_render_url")
    assert render_url is not None, "result page must include presentation_render_url when a render exists"
    assert render_url == f"/api/v1/design-runs/{run_id}/presentation-render/image"

    # The URL must be reachable and return the stored PNG bytes.
    image = client.get(render_url)
    assert image.status_code == 200
    assert image.content == PNG_BYTES


def test_unconfigured_render_never_invalidates_result(completed_run):
    client = completed_run["client"]
    render = client.get(f"/api/v1/design-runs/{completed_run['run_id']}/presentation-render").json()
    # The run-time attempt without a key recorded an explicit unconfigured
    # state (or a later mocked run completed) -- the run itself stayed done.
    assert render["status"] in ("unconfigured", "completed")
    run = client.get(f"/api/v1/design-runs/{completed_run['run_id']}").json()
    assert run["status"] == "completed_with_assumptions"


def test_share_token_flow_and_isolation(completed_run):
    client = completed_run["client"]
    app = completed_run["app"]
    created = client.post(f"/api/v1/projects/{completed_run['project_id']}/share")
    assert created.status_code == 201
    token = created.json()["share_token"]

    anonymous = TestClient(app)  # no session at all
    shared = anonymous.get(f"/api/v1/shared/{token}")
    assert shared.status_code == 200
    body = shared.json()
    text = json.dumps(body, ensure_ascii=False)
    # Sanitized: no coordinates, deed, owner, session, or filesystem paths.
    for forbidden in ("latitude", "owner", "deed", "session", "storage", "26.42", ":\\\\"):
        assert forbidden not in text
    kinds = {f["kind"] for f in body["files"]}
    # Only verified coordinate-free artifacts: the location-stamped PDFs and
    # the input-echoing run.json stay private (Codex demo round 1, P1).
    assert kinds <= {"dxf", "svg_plan", "svg_elevation"}
    assert "pdf" not in kinds and "sheet_pdf" not in kinds
    assert "run_json" not in kinds

    file_entry = next(f for f in body["files"] if f["kind"] == "svg_plan")
    download = anonymous.get(file_entry["url_path"])
    assert download.status_code == 200

    assert anonymous.get("/api/v1/shared/not-a-real-token").status_code == 404

    # Expired tokens become indistinguishable from unknown ones.
    with app.state.session_factory() as db:
        from sqlalchemy import select

        record = db.execute(select(ShareToken)).scalars().first()
        record.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert anonymous.get(f"/api/v1/shared/{token}").status_code == 404
    anonymous.close()


def test_pricing_endpoint(completed_run):
    price = completed_run["client"].get("/api/v1/pricing/current").json()
    assert price == {"label": "demo_concept_package", "currency": "SAR", "amount": 18000.0}


# ── Migration covers the new tables ─────────────────────────────────────────


def test_migration_creates_demo_tables_and_seed(tmp_path, monkeypatch):
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect, text

    root = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "demo_migration.db"
    monkeypatch.setenv("SPD_DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "src" / "saudi_plot_api" / "migrations"))
    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    tables = set(inspect(engine).get_table_names())
    assert {
        "project_documents",
        "plot_records",
        "design_briefs",
        "room_programs",
        "design_runs",
        "design_run_events",
        "output_files",
        "presentation_renders",
        "share_tokens",
        "pricing_configurations",
    } <= tables
    with engine.connect() as connection:
        count = connection.execute(
            text("SELECT COUNT(*) FROM pricing_configurations WHERE active = 1")
        ).scalar_one()
    assert count == 1
    engine.dispose()


# ── Codex demo round 1 regressions ──────────────────────────────────────────


def test_shared_files_contain_no_coordinates(completed_run):
    """Every byte served through a share link is free of the plot's exact
    coordinates (the PDFs embed them and must never be shareable)."""
    client = completed_run["client"]
    app = completed_run["app"]
    created = client.post(f"/api/v1/projects/{completed_run['project_id']}/share")
    token = created.json()["share_token"]
    anonymous = TestClient(app)
    body = anonymous.get(f"/api/v1/shared/{token}").json()
    assert body["files"], "share must still expose the design artifacts"
    for entry in body["files"]:
        content = anonymous.get(entry["url_path"]).content
        # The exact coordinate renderings the PDF writers emit ("lat 26.42",
        # "26.42000, 50.10000 (WGS84 ...)"), distinct from drawing geometry.
        for needle in (b"WGS84", b"26.42000", b"50.10000", b"lat 26.42", b"lon 50.1"):
            assert needle not in content, (entry["filename"], needle)
    anonymous.close()


def test_provider_http_200_with_non_json_body_is_structured(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            raise ValueError("not json")

    monkeypatch.setattr(gemini.httpx, "post", lambda *args, **kwargs: FakeResponse())
    settings = Settings(_env_file=None, environment="test", cookie_secure=False, gemini_api_key="k")
    with pytest.raises(gemini.GeminiError) as excinfo:
        gemini.extract_deed(settings, PNG_BYTES, "image/png")
    assert excinfo.value.code == "provider_bad_format"


def test_unexpected_extraction_crash_leaves_terminal_document(tmp_path, monkeypatch):
    """A crash mid-extraction must never strand the document in 'extracting'."""

    def boom(*args, **kwargs):
        raise RuntimeError("unexpected provider client crash")

    monkeypatch.setattr(gemini, "_post_generate", boom)
    app = build_app(make_settings(tmp_path, gemini_api_key="test-key"))
    with start_client(app) as client:
        pid = create_project(client)
        response = client.post(
            f"/api/v1/projects/{pid}/documents",
            files={"file": ("deed.png", io.BytesIO(PNG_BYTES), "image/png")},
        )
        assert response.status_code == 500  # honest internal error envelope
        assert response.json()["error"]["code"] == "internal_error"

        from sqlalchemy import select

        from saudi_plot_api.models import ProjectDocument

        with app.state.session_factory() as db:
            document = db.execute(select(ProjectDocument)).scalars().one()
            assert document.status == "extraction_failed"  # terminal, not stuck
            assert document.extraction_error_code == "extraction_internal_error"


# ── Codex demo round 2 regressions ──────────────────────────────────────────


def test_street_edge_derived_from_boundaries():
    from saudi_plot_api.services.engine import EngineInputs, _frontage

    def inputs(boundaries):
        return EngineInputs(
            width_m=20,
            height_m=30,
            latitude=None,
            longitude=None,
            street_width_m=None,
            boundaries=boundaries,
            answers=None,
            room_counts=None,
        )

    west = _frontage(inputs({"west": "42.5 م — على شارع عرض 41 م", "north": "70 م"}))
    assert west[0] == 3 and west[1] == 41.0 and west[2] == []

    # Widest street wins when several boundaries face streets, with a note.
    multi = _frontage(inputs({"north": "على شارع عرض 20 م", "south": "على شارع عرض 15 م"}))
    assert multi[0] == 2 and multi[1] == 20.0
    assert any("widest" in note for note in multi[2])

    # No street mentioned: explicit assumed-frontage note, edge 0.
    none = _frontage(inputs({"north": "70 م"}))
    assert none[0] == 0 and any("assumed" in note for note in none[2])


def test_late_assumptions_downgrade_supported(tmp_path):
    """A reference plot outside the demo zone must not be reported as plainly
    'supported': the pack-override assumption downgrades the status."""
    from saudi_plot_api.services import storage as storage_service
    from saudi_plot_api.services.engine import EngineInputs, plan_support, run_engine

    inputs = EngineInputs(
        width_m=20,
        height_m=30,
        latitude=26.42,
        longitude=50.10,
        street_width_m=15.0,
        boundaries={"south": "20 م — على شارع عرض 15 م"},
        answers=None,
        room_counts=None,
    )
    assert plan_support(inputs)[0] == "supported"  # pre-engine view

    root = storage_service.storage_root(tmp_path / "storage")
    out_dir = root / "projects" / "p" / "runs" / "r1"
    result = run_engine(inputs, out_dir, root, "r1")
    assert result.support_status == "supported_with_assumptions"
    assert any("outside the installed pack's demo zone" in a for a in result.assumptions)
    assert result.summary["street_edge_index"] == 0


def test_extraction_requires_boolean_deed_verdict(tmp_path, monkeypatch):
    for bad in ({}, {"is_valid_deed": "false"}, {"is_valid_deed": 1}):
        payload = {"candidates": [{"content": {"parts": [{"text": json.dumps(bad)}]}}]}
        monkeypatch.setattr(gemini, "_post_generate", lambda *a, _p=payload, **k: _p)
        settings = Settings(
            _env_file=None, environment="test", cookie_secure=False, gemini_api_key="k"
        )
        with pytest.raises(gemini.GeminiError) as excinfo:
            gemini.extract_deed(settings, PNG_BYTES, "image/png")
        assert excinfo.value.code == "provider_bad_format", bad


def test_render_exception_lands_terminal_failed(completed_run, monkeypatch):
    """An unexpected crash inside the render attempt must leave a terminal
    'failed' row, never a forever-'pending' one."""

    def boom(*args, **kwargs):
        raise OSError("disk error while reading the plan image")

    monkeypatch.setattr(gemini, "generate_presentation_render", boom)
    settings = completed_run["app"].state.settings
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    client = completed_run["client"]
    response = client.post(f"/api/v1/design-runs/{completed_run['run_id']}/presentation-render")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["error_code"] == "render_internal_error"

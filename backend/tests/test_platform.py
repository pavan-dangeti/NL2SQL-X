import sqlite3
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from google.genai import errors

from app import demo_data
from app.config import Settings
from app.limits import RateLimiter, TTLCache
from app.llm import DemoLLM, GeminiLLM, LLMUnavailableError, SqlDraft, create_llm
from app.main import client_ip, create_app
from app.service import Service
from app.store import Store


class FakeModels:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0
        self.seen = []

    async def generate_content(self, **kwargs):
        self.calls += 1
        self.seen.append((kwargs["model"], kwargs["config"].thinking_config))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def gemini(settings, *outcomes, **overrides) -> tuple[GeminiLLM, FakeModels]:
    update = {"gemini_api_key": "test-key", "llm_max_retries": 2, "gemini_fallback_model": None, **overrides}
    llm = GeminiLLM(settings.model_copy(update=update))
    models = FakeModels(*outcomes)
    llm._client = SimpleNamespace(aio=SimpleNamespace(models=models))
    return llm, models


def api_error(code: int, message: str = "x") -> errors.APIError:
    return errors.APIError(code, {"error": {"code": code, "message": message, "status": "X"}})


DRAFT = SqlDraft(answerable=True, sql="SELECT 1", explanation="one")


class TestGemini:
    async def test_returns_parsed_draft(self, settings):
        llm, models = gemini(settings, SimpleNamespace(parsed=DRAFT, text=None))
        assert await llm.draft("s", "p") == DRAFT and models.calls == 1

    async def test_falls_back_to_json_text(self, settings):
        llm, _ = gemini(settings, SimpleNamespace(parsed=None, text=DRAFT.model_dump_json()))
        assert (await llm.draft("s", "p")).sql == "SELECT 1"

    async def test_retries_transient_errors(self, settings, monkeypatch):
        monkeypatch.setattr("app.llm.asyncio.sleep", _no_sleep)
        llm, models = gemini(settings, api_error(503), api_error(429), SimpleNamespace(parsed=DRAFT, text=None))
        assert await llm.draft("s", "p") == DRAFT and models.calls == 3

    async def test_gives_up_after_retries(self, settings, monkeypatch):
        monkeypatch.setattr("app.llm.asyncio.sleep", _no_sleep)
        llm, models = gemini(settings, api_error(503), api_error(503), api_error(503))
        with pytest.raises(LLMUnavailableError, match="busy"):
            await llm.draft("s", "p")
        assert models.calls == 3

    async def test_auth_errors_are_not_retried(self, settings):
        llm, models = gemini(settings, api_error(403))
        with pytest.raises(LLMUnavailableError, match="API key"):
            await llm.draft("s", "p")
        assert models.calls == 1

    async def test_unreadable_output_is_reported(self, settings, monkeypatch):
        monkeypatch.setattr("app.llm.asyncio.sleep", _no_sleep)
        bad = SimpleNamespace(parsed=None, text="not json")
        llm, _ = gemini(settings, bad, bad, bad)
        with pytest.raises(LLMUnavailableError, match="unreadable"):
            await llm.draft("s", "p")

    async def test_rate_limit_falls_back_to_second_model(self, settings, monkeypatch):
        monkeypatch.setattr("app.llm.asyncio.sleep", _no_sleep)
        ok = SimpleNamespace(parsed=DRAFT, text=None)
        llm, models = gemini(
            settings, api_error(429), api_error(429), api_error(429), ok, gemini_fallback_model="gemini-lite"
        )
        assert await llm.draft("s", "p") == DRAFT
        assert [m for m, _ in models.seen] == ["gemini-3.8-flash"] * 3 + ["gemini-lite"]

    async def test_rate_limit_message_when_all_models_are_exhausted(self, settings, monkeypatch):
        monkeypatch.setattr("app.llm.asyncio.sleep", _no_sleep)
        llm, _ = gemini(settings, *[api_error(429)] * 6, gemini_fallback_model="gemini-lite")
        with pytest.raises(LLMUnavailableError, match="rate limit"):
            await llm.draft("s", "p")

    async def test_unsupported_thinking_level_is_dropped(self, settings):
        ok = SimpleNamespace(parsed=DRAFT, text=None)
        llm, models = gemini(
            settings, api_error(400, "thinking_level is not supported"), ok, gemini_thinking_level="low"
        )
        assert await llm.draft("s", "p") == DRAFT
        assert models.seen[0][1] is not None and models.seen[1][1] is None

    async def test_server_retry_delay_is_respected(self, settings, monkeypatch):
        waits = []

        async def record(seconds):
            waits.append(seconds)

        monkeypatch.setattr("app.llm.asyncio.sleep", record)
        ok = SimpleNamespace(parsed=DRAFT, text=None)
        llm, _ = gemini(settings, api_error(429, "Please retry in 3.5s."), ok)
        await llm.draft("s", "p")
        assert waits == [3.5]


async def _no_sleep(_):
    return None


def test_provider_selection(settings):
    assert isinstance(create_llm(settings), DemoLLM)
    assert isinstance(create_llm(settings.model_copy(update={"llm_provider": "gemini"})), DemoLLM)
    assert isinstance(
        create_llm(settings.model_copy(update={"llm_provider": "gemini", "gemini_api_key": "k"})), GeminiLLM
    )


@pytest.mark.parametrize(
    "overrides",
    [{"llm_provider": "gemini", "gemini_api_key": None}, {"llm_provider": "demo", "cors_origins": "*"}],
)
def test_production_config_is_validated(tmp_path, overrides):
    with pytest.raises(ValueError):
        Settings(environment="production", data_dir=tmp_path, _env_file=None, **overrides)


def test_cors_origins_parse_from_csv(tmp_path):
    s = Settings(cors_origins="https://a.app, https://b.app", data_dir=tmp_path, _env_file=None)
    assert s.cors_origins == ["https://a.app", "https://b.app"]


class TestDemoData:
    def test_build_is_deterministic_and_anchored_to_today(self, tmp_path):
        a, b = tmp_path / "a.db", tmp_path / "b.db"
        demo_data.build(a, date(2026, 1, 31))
        demo_data.build(b, date(2026, 1, 31))
        dump = [list(sqlite3.connect(p).iterdump()) for p in (a, b)]
        assert dump[0] == dump[1]
        latest = sqlite3.connect(a).execute("SELECT MAX(order_date) FROM orders").fetchone()[0]
        assert latest <= "2026-01-31"

    def test_ensure_rebuilds_only_when_stale(self, tmp_path):
        path = tmp_path / "d.db"
        assert demo_data.ensure(path, date(2026, 1, 1)) is True
        assert demo_data.ensure(path, date(2026, 1, 1)) is False
        assert demo_data.ensure(path, date(2026, 1, 2)) is True
        assert demo_data.built_on(path) == date(2026, 1, 2)

    def test_totals_match_line_items(self, tmp_path):
        path = tmp_path / "d.db"
        demo_data.build(path, date(2026, 6, 1))
        diff = (
            sqlite3.connect(path)
            .execute(
                "SELECT MAX(ABS(o.total_amount - s.t)) FROM orders o JOIN (SELECT order_id, "
                "SUM(quantity * unit_price * (1 - discount)) AS t FROM order_items GROUP BY order_id) s "
                "ON s.order_id = o.id"
            )
            .fetchone()[0]
        )
        assert diff < 0.01


def test_cache_expires_and_evicts(monkeypatch):
    now = [100.0]
    monkeypatch.setattr("app.limits.time.monotonic", lambda: now[0])
    cache = TTLCache(maxsize=2, ttl_s=10)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)
    assert cache.get("a") is None and cache.get("c") == 3
    now[0] += 11
    assert cache.get("c") is None


def test_rate_limiter_window(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("app.limits.time.monotonic", lambda: now[0])
    limiter = RateLimiter(per_minute=2)
    assert limiter.hit("ip") is None and limiter.hit("ip") is None
    assert limiter.hit("ip") == 60
    assert limiter.hit("other") is None
    now[0] = 61
    assert limiter.hit("ip") is None


@pytest.mark.parametrize(
    ("header", "hops", "expected"),
    [
        ("", 0, "testclient"),
        ("1.1.1.1", 0, "testclient"),
        ("6.6.6.6, 1.1.1.1", 1, "1.1.1.1"),
        ("6.6.6.6, 1.1.1.1, 10.0.0.1", 2, "1.1.1.1"),
        ("1.1.1.1", 2, "testclient"),
    ],
)
def test_client_ip_trusts_only_configured_hops(header, hops, expected):
    request = SimpleNamespace(client=SimpleNamespace(host="testclient"), headers={"x-forwarded-for": header})
    assert client_ip(request, hops) == expected


def test_serves_built_frontend_with_spa_fallback(settings, tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "assets" / "app.js").write_text("js")
    monkeypatch.setattr("app.main.FRONTEND_DIST", dist)
    s = settings.model_copy(update={"serve_frontend": True})
    with TestClient(create_app(s, Service(s, Store(s.app_db_path), DemoLLM()))) as client:
        assert client.get("/").text == "<html>app</html>"
        assert client.get("/history/anything").text == "<html>app</html>"
        asset = client.get("/assets/app.js")
        assert asset.text == "js" and "immutable" in asset.headers["cache-control"]
        assert client.get("/api/v1/unknown").status_code == 404
        assert client.get("/../../etc/passwd").text == "<html>app</html>"


def test_expired_uploads_are_removed_on_startup(settings):
    store = Store(settings.app_db_path)
    service = Service(settings, store, DemoLLM())
    service.startup()
    service.path("ds_old").write_bytes(b"x")
    store.add_dataset(id="ds_old", name="old", owner="client-aaaa-1111", tables=["t"], row_count=1, size_bytes=1)
    store._conn.execute("UPDATE datasets SET created_at = '2000-01-01T00:00:00+00:00' WHERE id = 'ds_old'")
    service.startup()
    assert store.get_dataset("ds_old") is None and not service.path("ds_old").exists()
    store.close()

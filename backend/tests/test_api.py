import asyncio

import pytest

from app.llm import LLMUnavailableError, SqlDraft
from tests.conftest import CLIENT, OTHER, ScriptedLLM, ok

CSV = b"region,month,revenue\nEU,2026-01,10\nUS,2026-01,20\nEU,2026-02,15\n"


def upload(client, headers=CLIENT, files=None, name="Sales"):
    files = files or [("files", ("sales.csv", CSV, "text/csv"))]
    return client.post("/api/v1/datasets", headers=headers, files=files, data={"name": name})


class TestHealthAndMeta:
    def test_live_and_ready(self, client):
        assert client.get("/health/live").json() == {"status": "ok"}
        ready = client.get("/health/ready").json()
        assert ready["status"] == "ok" and ready["llm"] == "demo"

    def test_meta_reports_demo_mode(self, client):
        meta = client.get("/api/v1/meta").json()
        assert meta["demo_mode"] is True and meta["version"]

    def test_security_headers_and_request_id(self, client):
        r = client.get("/health/live", headers={"X-Request-Id": "abc-123"})
        assert r.headers["X-Request-Id"] == "abc-123"
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["X-Frame-Options"] == "DENY"

    def test_malicious_request_id_is_replaced(self, client):
        r = client.get("/health/live", headers={"X-Request-Id": "<script>"})
        assert r.headers["X-Request-Id"] != "<script>"


class TestClientId:
    @pytest.mark.parametrize("headers", [{}, {"X-Client-Id": "short"}, {"X-Client-Id": "bad id with spaces!!"}])
    def test_required_and_validated(self, client, headers):
        r = client.get("/api/v1/datasets", headers=headers)
        assert r.status_code == 400


class TestQuery:
    def test_answers_sample_question(self, client):
        r = client.post("/api/v1/query", headers=CLIENT, json={"question": "Revenue by month for the last 12 months"})
        body = r.json()
        assert r.status_code == 200
        assert body["columns"] == ["month", "revenue"]
        assert body["row_count"] == 12
        assert body["chart"]["type"] == "line"
        assert body["sql_pretty"].startswith("SELECT")
        assert body["explanation"] and body["model"] == "demo"
        assert set(body["timings"]) == {"llm_ms", "db_ms", "total_ms"}

    def test_every_suggestion_returns_rows(self, client):
        for question in client.get("/api/v1/datasets/ecommerce/suggestions", headers=CLIENT).json():
            body = client.post("/api/v1/query", headers=CLIENT, json={"question": question}).json()
            assert body["row_count"] > 0, question

    def test_question_is_normalised_and_validated(self, client):
        assert client.post("/api/v1/query", headers=CLIENT, json={"question": "   "}).status_code == 422
        assert client.post("/api/v1/query", headers=CLIENT, json={"question": "x" * 501}).status_code == 422
        r = client.post("/api/v1/query", headers=CLIENT, json={"question": "  top 10   products by REVENUE?  "})
        assert r.status_code == 200

    def test_validation_errors_are_readable(self, client):
        r = client.post("/api/v1/query", headers=CLIENT, json={})
        assert r.json()["code"] == "invalid_request" and "question" in r.json()["detail"]

    def test_unanswerable_question(self, client):
        r = client.post("/api/v1/query", headers=CLIENT, json={"question": "What is the meaning of life?"})
        assert r.status_code == 422 and r.json()["code"] == "unanswerable"

    def test_unknown_dataset_is_404(self, client):
        r = client.post("/api/v1/query", headers=CLIENT, json={"question": "q", "dataset_id": "nope"})
        assert r.status_code == 404
        r = client.post("/api/v1/query", headers=CLIENT, json={"question": "q", "dataset_id": "../../etc"})
        assert r.status_code == 404

    def test_repeat_question_is_served_from_cache(self, make_client):
        llm = ScriptedLLM(ok("SELECT COUNT(*) AS n FROM orders"))
        client = make_client(llm)
        first = client.post("/api/v1/query", headers=CLIENT, json={"question": "How many orders?"}).json()
        second = client.post("/api/v1/query", headers=CLIENT, json={"question": "how many orders"}).json()
        assert first["cached"] is False and second["cached"] is True
        assert len(llm.prompts) == 1
        assert second["rows"] == first["rows"]

    def test_follow_up_sends_previous_turn(self, make_client):
        llm = ScriptedLLM(ok("SELECT COUNT(*) AS n FROM orders WHERE channel = 'Web'"))
        client = make_client(llm)
        previous = {"question": "How many orders?", "sql": "SELECT COUNT(*) FROM orders"}
        r = client.post("/api/v1/query", headers=CLIENT, json={"question": "only web", "previous": previous})
        assert r.status_code == 200
        assert "Previous SQL:\nSELECT COUNT(*) FROM orders" in llm.prompts[0][1]

    def test_prompt_contains_schema_profile_and_rules(self, make_client):
        llm = ScriptedLLM(ok("SELECT 1 AS x FROM orders LIMIT 1"))
        make_client(llm).post("/api/v1/query", headers=CLIENT, json={"question": "anything"})
        system = llm.prompts[0][0]
        assert "TABLE orders" in system and "'Delivered'" in system and '"Today" is' in system

    def test_broken_sql_is_repaired_once(self, make_client):
        llm = ScriptedLLM(ok("SELECT nope FROM orders"), ok("SELECT COUNT(*) AS n FROM orders"))
        client = make_client(llm)
        body = client.post("/api/v1/query", headers=CLIENT, json={"question": "count orders"}).json()
        assert body["repaired"] is True and body["rows"][0][0] > 0
        assert "no such column: nope" in llm.prompts[1][1]

    def test_unsafe_sql_is_repaired_or_refused(self, make_client):
        client = make_client(ScriptedLLM(ok("DELETE FROM orders")))
        r = client.post("/api/v1/query", headers=CLIENT, json={"question": "remove everything"})
        assert r.status_code == 400 and r.json()["code"] == "unsafe_sql"
        rows = client.post("/api/v1/sql", headers=CLIENT, json={"sql": "SELECT COUNT(*) FROM orders"}).json()
        assert rows["rows"][0][0] > 0

    def test_persistent_sql_error_is_422(self, make_client):
        client = make_client(ScriptedLLM(ok("SELECT nope FROM orders")))
        r = client.post("/api/v1/query", headers=CLIENT, json={"question": "q"})
        assert r.status_code == 422 and r.json()["code"] == "sql_error"

    def test_llm_outage_is_503(self, make_client):
        client = make_client(ScriptedLLM(LLMUnavailableError("The AI service is busy.")))
        r = client.post("/api/v1/query", headers=CLIENT, json={"question": "q"})
        assert r.status_code == 503 and r.json()["detail"] == "The AI service is busy."

    def test_unexpected_error_is_hidden(self, make_client):
        client = make_client(ScriptedLLM(RuntimeError("secret internals")), raise_errors=False)
        r = client.post("/api/v1/query", headers=CLIENT, json={"question": "q"})
        assert r.status_code == 500 and "secret" not in r.text

    def test_row_cap_is_applied(self, make_client):
        client = make_client(ScriptedLLM(ok("SELECT * FROM orders")), max_result_rows=25)
        body = client.post("/api/v1/query", headers=CLIENT, json={"question": "all orders"}).json()
        assert body["row_count"] == 25 and body["truncated"] is True
        assert body["chart"]["type"] == "line"

    def test_rate_limit(self, make_client):
        client = make_client(rate_limit_per_minute=3)
        codes = [
            client.post("/api/v1/query", headers=CLIENT, json={"question": "Top 10 products by revenue"}).status_code
            for _ in range(4)
        ]
        assert codes == [200, 200, 200, 429]


class TestRunSql:
    def test_runs_edited_sql(self, client):
        r = client.post("/api/v1/sql", headers=CLIENT, json={"sql": "SELECT name FROM regions ORDER BY name"})
        assert r.status_code == 200 and r.json()["row_count"] == 6

    @pytest.mark.parametrize("sql", ["DROP TABLE orders", "SELECT * FROM _meta", "SELECT 1; SELECT 2"])
    def test_rejects_unsafe_sql(self, client, sql):
        assert client.post("/api/v1/sql", headers=CLIENT, json={"sql": sql}).status_code == 400


class TestHistory:
    def test_history_is_recorded_per_client(self, client):
        client.post("/api/v1/query", headers=CLIENT, json={"question": "Top 10 products by revenue"})
        client.post("/api/v1/query", headers=CLIENT, json={"question": "gibberish question"})
        mine = client.get("/api/v1/history", headers=CLIENT).json()
        assert [h["status"] for h in mine] == ["error", "ok"]
        assert client.get("/api/v1/history", headers=OTHER).json() == []

    def test_clear_history(self, client):
        client.post("/api/v1/query", headers=CLIENT, json={"question": "Top 10 products by revenue"})
        assert client.delete("/api/v1/history", headers=CLIENT).status_code == 204
        assert client.get("/api/v1/history", headers=CLIENT).json() == []


class TestDatasets:
    def test_builtin_dataset_is_listed_with_schema(self, client):
        datasets = client.get("/api/v1/datasets", headers=CLIENT).json()
        assert datasets[0]["id"] == "ecommerce" and datasets[0]["builtin"] is True
        assert "owner" not in datasets[0]
        tables = client.get("/api/v1/datasets/ecommerce/schema", headers=CLIENT).json()["tables"]
        assert {t["name"] for t in tables} == {"customers", "orders", "order_items", "products", "regions"}

    def test_upload_query_and_isolation(self, client):
        r = upload(client)
        assert r.status_code == 201
        ds = r.json()
        assert ds["name"] == "Sales" and ds["tables"] == ["sales"] and ds["row_count"] == 3
        body = client.post(
            "/api/v1/query", headers=CLIENT, json={"question": "How many rows are in sales", "dataset_id": ds["id"]}
        ).json()
        assert body["rows"] == [[3]]
        assert client.get(f"/api/v1/datasets/{ds['id']}/schema", headers=OTHER).status_code == 404
        assert [d["id"] for d in client.get("/api/v1/datasets", headers=OTHER).json()] == ["ecommerce"]
        suggestions = client.get(f"/api/v1/datasets/{ds['id']}/suggestions", headers=CLIENT).json()
        assert "Show the first 20 rows of sales" in suggestions

    def test_uploaded_dataset_cannot_read_builtin_tables(self, client):
        ds = upload(client).json()
        r = client.post("/api/v1/sql", headers=CLIENT, json={"sql": "SELECT * FROM orders", "dataset_id": ds["id"]})
        assert r.status_code == 400

    def test_delete_dataset(self, client):
        ds = upload(client).json()
        assert client.delete(f"/api/v1/datasets/{ds['id']}", headers=OTHER).status_code == 404
        assert client.delete(f"/api/v1/datasets/{ds['id']}", headers=CLIENT).status_code == 204
        assert client.get(f"/api/v1/datasets/{ds['id']}/schema", headers=CLIENT).status_code == 404
        assert client.delete("/api/v1/datasets/ecommerce", headers=CLIENT).status_code == 404

    @pytest.mark.parametrize(
        ("files", "status"),
        [
            ([("files", ("notes.pdf", b"%PDF", "application/pdf"))], 400),
            ([("files", ("empty.csv", b"", "text/csv"))], 400),
            ([("files", ("h.csv", b"a,b\n", "text/csv"))], 400),
        ],
    )
    def test_rejects_bad_uploads(self, client, files, status):
        assert upload(client, files=files).status_code == status

    def test_upload_size_limit(self, make_client):
        client = make_client(max_upload_mb=1)
        big = b"a,b\n" + b"1234567890,abcdefghij\n" * 60_000
        assert upload(client, files=[("files", ("big.csv", big, "text/csv"))]).status_code == 413

    def test_dataset_quota(self, make_client):
        client = make_client(max_datasets_per_client=1)
        assert upload(client).status_code == 201
        assert upload(client).status_code == 409


async def test_concurrent_identical_questions_share_one_llm_call(settings):
    from app.service import Service
    from app.store import Store

    class SlowLLM(ScriptedLLM):
        async def draft(self, system, prompt):
            await asyncio.sleep(0.05)
            return await super().draft(system, prompt)

    llm = SlowLLM(SqlDraft(answerable=True, sql="SELECT COUNT(*) FROM orders", explanation="x"))
    service = Service(settings, Store(settings.app_db_path), llm)
    service.startup()
    results = await asyncio.gather(*(service.ask("count orders", "ecommerce", "client-aaaa-1111") for _ in range(10)))
    assert len(llm.prompts) == 1
    assert sum(not r["cached"] for r in results) == 1
    service.store.close()

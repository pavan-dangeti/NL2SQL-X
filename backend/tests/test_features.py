import json

import pytest

from app.insights import summarize
from app.llm import LLMUnavailableError
from tests.conftest import CLIENT, OTHER, ScriptedLLM, ok

STREAM = {**CLIENT, "Accept": "text/event-stream"}


def events(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = [line for line in block.splitlines() if not line.startswith(":")]
        if not lines:
            continue
        kind = lines[0].removeprefix("event: ")
        out.append((kind, json.loads(lines[1].removeprefix("data: "))))
    return out


class TestStreaming:
    def test_streams_stages_then_result(self, client):
        r = client.post("/api/v1/query", headers=STREAM, json={"question": "Top 10 products by revenue"})
        assert r.headers["content-type"].startswith("text/event-stream")
        got = events(r.text)
        stages = [d["stage"] for k, d in got if k == "stage"]
        assert stages == ["schema", "generating", "validating", "running", "done"]
        kind, result = got[-1]
        assert kind == "result" and result["row_count"] == 10 and result["insights"]

    def test_cached_answer_reports_cache_stage(self, client):
        client.post("/api/v1/query", headers=CLIENT, json={"question": "Top 10 products by revenue"})
        got = events(client.post("/api/v1/query", headers=STREAM, json={"question": "Top 10 products by revenue"}).text)
        assert ("stage", {"stage": "cache"}) in got and got[-1][1]["cached"] is True

    def test_repair_stage_is_reported(self, make_client):
        client = make_client(ScriptedLLM(ok("SELECT nope FROM orders"), ok("SELECT COUNT(*) AS n FROM orders")))
        got = events(client.post("/api/v1/query", headers=STREAM, json={"question": "q"}).text)
        assert "repairing" in [d.get("stage") for k, d in got if k == "stage"]
        assert got[-1][1]["repaired"] is True

    @pytest.mark.parametrize(
        ("llm", "status", "code"),
        [
            (ScriptedLLM(ok("DROP TABLE orders")), 400, "unsafe_sql"),
            (ScriptedLLM(LLMUnavailableError("busy")), 503, "llm_unavailable"),
            (ScriptedLLM(RuntimeError("boom")), 500, "internal"),
        ],
    )
    def test_errors_are_streamed(self, make_client, llm, status, code):
        got = events(make_client(llm).post("/api/v1/query", headers=STREAM, json={"question": "q"}).text)
        kind, body = got[-1]
        assert kind == "error" and body["status"] == status and body["code"] == code
        assert "boom" not in body["detail"]

    def test_unknown_dataset_fails_as_error_event(self, client):
        got = events(client.post("/api/v1/query", headers=STREAM, json={"question": "q", "dataset_id": "nope"}).text)
        assert got[-1][0] == "error" and got[-1][1]["status"] == 404


class TestPins:
    def pin(self, client, headers=CLIENT, **overrides):
        body = {
            "dataset_id": "ecommerce",
            "title": "Monthly revenue",
            "question": "Revenue by month",
            "sql": "SELECT strftime('%Y-%m', order_date) AS month, SUM(total_amount) AS revenue FROM orders "
            "GROUP BY month ORDER BY month",
            "chart_type": "area",
            **overrides,
        }
        return client.post("/api/v1/pins", headers=headers, json=body)

    def test_pin_list_run_rename_delete(self, client):
        pin = self.pin(client).json()
        assert pin["id"].startswith("pin_") and pin["chart_type"] == "area"
        assert [p["id"] for p in client.get("/api/v1/pins", headers=CLIENT).json()] == [pin["id"]]
        run = client.post(f"/api/v1/pins/{pin['id']}/run", headers=CLIENT).json()
        assert run["pin"]["id"] == pin["id"] and run["result"]["row_count"] > 1
        assert (
            client.patch(f"/api/v1/pins/{pin['id']}", headers=CLIENT, json={"title": "  Revenue  trend "}).status_code
            == 204
        )
        assert client.get("/api/v1/pins", headers=CLIENT).json()[0]["title"] == "Revenue trend"
        assert client.delete(f"/api/v1/pins/{pin['id']}", headers=CLIENT).status_code == 204
        assert client.get("/api/v1/pins", headers=CLIENT).json() == []

    def test_pins_are_private(self, client):
        pin = self.pin(client).json()
        assert client.get("/api/v1/pins", headers=OTHER).json() == []
        assert client.post(f"/api/v1/pins/{pin['id']}/run", headers=OTHER).status_code == 404
        assert client.delete(f"/api/v1/pins/{pin['id']}", headers=OTHER).status_code == 404
        assert client.patch(f"/api/v1/pins/{pin['id']}", headers=OTHER, json={"title": "x"}).status_code == 404

    def test_pin_sql_is_validated(self, client):
        assert self.pin(client, sql="DELETE FROM orders").status_code == 400
        assert self.pin(client, chart_type="radar").status_code == 422

    def test_pin_title_defaults_to_question(self, client):
        assert self.pin(client, title="   ").json()["title"] == "Revenue by month"

    def test_pin_limit(self, client, monkeypatch):
        monkeypatch.setattr("app.service.MAX_PINS", 2)
        assert [self.pin(client).status_code for _ in range(3)] == [201, 201, 409]

    def test_deleting_dataset_removes_its_pins(self, client):
        ds = client.post(
            "/api/v1/datasets", headers=CLIENT, files=[("files", ("t.csv", b"a,b\nx,1\ny,2\n", "text/csv"))]
        ).json()
        pin = self.pin(client, dataset_id=ds["id"], sql="SELECT a, b FROM t").json()
        client.delete(f"/api/v1/datasets/{ds['id']}", headers=CLIENT)
        assert client.post(f"/api/v1/pins/{pin['id']}/run", headers=CLIENT).status_code == 404


class TestPreview:
    def test_preview_table(self, client):
        r = client.get("/api/v1/datasets/ecommerce/tables/products/preview?limit=5", headers=CLIENT)
        body = r.json()
        assert r.status_code == 200 and body["row_count"] == 5 and body["chart"]["type"] == "table"
        assert body["columns"][:3] == ["id", "name", "category"]

    @pytest.mark.parametrize("table", ["_meta", "sqlite_master", "nope", "products; DROP TABLE x"])
    def test_preview_rejects_unknown_tables(self, client, table):
        assert client.get(f"/api/v1/datasets/ecommerce/tables/{table}/preview", headers=CLIENT).status_code == 404

    def test_preview_limit_is_bounded(self, client):
        assert (
            client.get("/api/v1/datasets/ecommerce/tables/products/preview?limit=500", headers=CLIENT).status_code
            == 422
        )


class TestInsights:
    def test_trend_insights(self):
        out = summarize(["month", "revenue"], [["2026-01", 100.0], ["2026-02", 150.0], ["2026-03", 120.0]])
        assert out[0] == "Revenue is up 20.0% from 2026-01 to 2026-03."
        assert "Peak revenue was 150 in 2026-02" in out[1]
        assert out[2] == "2026-03 changed -20.0% versus 2026-02."

    def test_ranking_insights(self):
        rows = [["A", 50], ["B", 20], ["C", 15], ["D", 10], ["E", 5]]
        out = summarize(["region", "revenue"], rows, {"type": "bar", "x": "region", "y": ["revenue"]})
        assert out == [
            "A leads with 50 (50.0% of the total revenue).",
            "The top 3 account for 85.0% of revenue.",
            "E is lowest at 5.",
        ]

    def test_negative_values_and_large_numbers(self):
        out = summarize(
            ["team", "delta"], [["x", -2_500_000], ["y", 12_000]], {"type": "bar", "x": "team", "y": ["delta"]}
        )
        assert out == ["y has the highest delta at 12.0K.", "x is lowest at -2.50M."]

    def test_averages_are_not_summed_into_shares(self):
        out = summarize(
            ["channel", "avg_order_value"],
            [["Web", 400], ["App", 380]],
            {"type": "bar", "x": "channel", "y": ["avg_order_value"]},
        )
        assert out == ["Web has the highest avg order value at 400.", "App is lowest at 380."]

    @pytest.mark.parametrize(
        ("columns", "rows"),
        [(["revenue"], [[5]]), (["name", "email"], [["a", "b"], ["c", "d"]]), (["month", "v"], [["2026-01", 1]])],
    )
    def test_no_insights_when_nothing_to_say(self, columns, rows):
        assert summarize(columns, rows) == []

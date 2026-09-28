import json
import re

import pytest
from playwright.sync_api import Page, expect

REVENUE = "Revenue by month for the last 12 months"
TOP = "Top 10 products by revenue"
REGION = "Revenue share by region"
TOTAL = "Total revenue this year"
CSV = "region,month,revenue\nEU,2026-01,10\nUS,2026-01,20\nEU,2026-02,15\nIN,2026-02,8\n"


def ask(page: Page, question: str) -> None:
    page.get_by_test_id("question-input").fill(question)
    page.get_by_test_id("question-input").press("Enter")


def open_app(page: Page) -> None:
    page.goto("/")
    expect(page.get_by_test_id("welcome")).to_be_visible()
    expect(page.get_by_test_id("suggestion").first).to_be_visible()


class TestAsking:
    def test_home_shows_schema_suggestions_and_demo_badge(self, page: Page):
        open_app(page)
        expect(page.get_by_test_id("suggestion")).to_have_count(8)
        for table in ["customers", "order_items", "orders", "products", "regions"]:
            expect(page.get_by_test_id(f"table-{table}")).to_be_visible()
        expect(page.get_by_text("Demo mode", exact=True)).to_be_visible()

    def test_suggestion_renders_line_chart_with_insights(self, page: Page):
        open_app(page)
        page.get_by_test_id("suggestion").filter(has_text=REVENUE).click()
        expect(page.get_by_test_id("chart-line")).to_be_visible()
        expect(page.get_by_test_id("result-title")).to_have_text(REVENUE)
        expect(page.get_by_test_id("insights")).to_contain_text("Peak revenue")
        expect(page.get_by_test_id("result-stats")).to_contain_text("12 rows")
        expect(page.locator(".recharts-line-curve")).to_have_count(1)

    def test_every_view_switch_works(self, page: Page):
        open_app(page)
        ask(page, TOP)
        expect(page.get_by_test_id("chart-bar")).to_be_visible()
        for view, marker in [
            ("line", "chart-line"),
            ("area", "chart-area"),
            ("pie", "chart-pie"),
            ("table", "results-table"),
            ("sql", "sql-code"),
            ("bar", "chart-bar"),
        ]:
            page.get_by_test_id(f"view-{view}").click()
            expect(page.get_by_test_id(marker)).to_be_visible()

    def test_measure_toggle_adds_a_series(self, page: Page):
        open_app(page)
        ask(page, "Average order value by channel")
        expect(page.get_by_test_id("chart-bar")).to_be_visible()
        expect(page.locator(".recharts-bar")).to_have_count(1)
        page.get_by_test_id("measures").get_by_role("button", name="Orders").click()
        expect(page.locator(".recharts-bar")).to_have_count(2)

    def test_metric_summary(self, page: Page):
        open_app(page)
        ask(page, TOTAL)
        expect(page.get_by_test_id("metric")).to_contain_text("Revenue")

    def test_repeat_question_is_cached(self, page: Page):
        open_app(page)
        ask(page, REGION)
        expect(page.get_by_test_id("chart-pie")).to_be_visible()
        ask(page, REGION)
        expect(page.get_by_test_id("result-stats")).to_contain_text("cached")

    def test_unanswerable_question_shows_error_without_retry(self, page: Page):
        open_app(page)
        ask(page, "What will the weather be tomorrow?")
        expect(page.get_by_test_id("error")).to_contain_text("Demo mode only answers")
        expect(page.get_by_test_id("retry")).to_have_count(0)

    def test_edit_and_run_sql(self, page: Page):
        open_app(page)
        ask(page, TOP)
        page.get_by_test_id("view-sql").click()
        page.get_by_test_id("edit-sql").click()
        page.get_by_test_id("sql-editor").fill("SELECT name, country FROM regions ORDER BY name")
        page.get_by_test_id("run-sql").click()
        expect(page.get_by_test_id("result-stats")).to_contain_text("6 rows")
        expect(page.get_by_test_id("results-table")).to_contain_text("United Arab Emirates")

    @pytest.mark.parametrize(
        ("sql", "message"),
        [
            ("DELETE FROM orders", "Only read-only SELECT"),
            ("SELECT * FROM sqlite_master", "restricted table"),
            ("SELECT nope FROM orders", "no such column"),
        ],
    )
    def test_unsafe_or_broken_sql_is_refused(self, page: Page, sql, message):
        open_app(page)
        ask(page, TOP)
        page.get_by_test_id("view-sql").click()
        page.get_by_test_id("edit-sql").click()
        page.get_by_test_id("sql-editor").fill(sql)
        page.get_by_test_id("sql-editor").press("Control+Enter")
        expect(page.get_by_test_id("error")).to_contain_text(message)

    def test_downloads(self, page: Page, tmp_path):
        open_app(page)
        ask(page, TOP)
        expect(page.get_by_test_id("chart-bar")).to_be_visible()
        page.wait_for_timeout(600)
        with page.expect_download() as csv:
            page.get_by_test_id("export-csv").click()
        lines = open(csv.value.path(), encoding="utf-8").read().splitlines()
        assert lines[0] == "product,category,revenue" and len(lines) == 11
        with page.expect_download() as js:
            page.get_by_test_id("export-json").click()
        data = json.load(open(js.value.path()))
        assert len(data) == 10 and set(data[0]) == {"product", "category", "revenue"}
        with page.expect_download() as png:
            page.get_by_test_id("export-png").click()
        assert open(png.value.path(), "rb").read(8) == b"\x89PNG\r\n\x1a\n"
        assert png.value.suggested_filename == "top-10-products-by-revenue.png"

    def test_copy_sql_and_share_link(self, page: Page, base_url):
        open_app(page)
        ask(page, TOP)
        page.get_by_test_id("share").click()
        expect(page.get_by_test_id("toast")).to_contain_text("Link copied")
        link = page.evaluate("navigator.clipboard.readText()")
        assert link.startswith(base_url) and "q=Top+10+products+by+revenue" in link
        page.get_by_test_id("view-sql").click()
        page.get_by_test_id("copy-sql").click()
        assert page.evaluate("navigator.clipboard.readText()").startswith("SELECT")

    def test_shared_link_runs_the_question(self, page: Page):
        page.goto("/?q=Revenue%20share%20by%20region")
        expect(page.get_by_test_id("chart-pie")).to_be_visible()
        expect(page).to_have_url(re.compile(r"/$|/#/$"))

    def test_follow_up_sends_context(self, page: Page):
        open_app(page)
        ask(page, TOP)
        expect(page.get_by_test_id("chart-bar")).to_be_visible()
        page.get_by_test_id("follow-up").check()
        with page.expect_request("**/api/v1/query") as req:
            ask(page, REGION)
        assert req.value.post_data_json["previous"]["question"] == TOP
        expect(page.get_by_test_id("chart-pie")).to_be_visible()
        expect(page.get_by_test_id("follow-up")).not_to_be_checked()


class TestSidebar:
    def test_schema_details_and_insert_column(self, page: Page):
        open_app(page)
        page.get_by_test_id("table-orders").click()
        page.get_by_role("button", name="status").click()
        expect(page.get_by_test_id("question-input")).to_have_value("status ")

    def test_table_preview(self, page: Page):
        open_app(page)
        page.get_by_test_id("preview-products").click()
        expect(page.get_by_test_id("result-title")).to_have_text("Preview of products")
        expect(page.get_by_test_id("result-stats")).to_contain_text("29 rows")
        expect(page.get_by_test_id("share")).to_have_count(0)

    def test_history_rerun_search_and_clear(self, page: Page):
        open_app(page)
        for q in [TOP, REGION, TOTAL]:
            ask(page, q)
            expect(page.get_by_test_id("result-title")).to_have_text(q)
        history = page.get_by_test_id("history")
        expect(history.get_by_role("button")).to_have_count(3)
        history.get_by_role("button", name=re.compile(TOP)).click()
        expect(page.get_by_test_id("result-title")).to_have_text(TOP)
        page.get_by_test_id("clear-history").click()
        expect(history).to_contain_text("Questions you ask will appear here")


class TestDashboard:
    def test_pin_rename_refresh_and_remove(self, page: Page):
        open_app(page)
        ask(page, REVENUE)
        page.get_by_test_id("view-area").click()
        page.get_by_test_id("pin").click()
        expect(page.get_by_test_id("toast")).to_contain_text("Pinned")
        ask(page, TOTAL)
        page.get_by_test_id("pin").click()
        page.get_by_test_id("nav-dashboard").click()
        cards = page.get_by_test_id("pin-card")
        expect(cards).to_have_count(2)
        expect(cards.first.get_by_test_id("chart-area")).to_be_visible()
        expect(cards.nth(1).get_by_test_id("metric")).to_be_visible()
        cards.first.get_by_role("button", name="Rename pin").click()
        cards.first.get_by_role("textbox", name="Pin title").fill("Monthly revenue")
        cards.first.get_by_role("button", name="Save title").click()
        expect(cards.first).to_contain_text("Monthly revenue")
        with page.expect_response("**/run") as resp:
            page.get_by_test_id("refresh-all").click()
        assert resp.value.ok
        cards.nth(1).get_by_test_id("unpin").click()
        expect(cards).to_have_count(1)
        page.reload()
        expect(page.get_by_test_id("pin-card")).to_have_count(1)

    def test_empty_dashboard_links_back(self, page: Page):
        page.goto("/#/dashboard")
        expect(page.get_by_test_id("dashboard-empty")).to_be_visible()
        page.get_by_role("button", name="Ask a question").click()
        expect(page.get_by_test_id("question-input")).to_be_focused()


class TestUpload:
    def test_upload_query_and_delete(self, page: Page, tmp_path):
        open_app(page)
        path = tmp_path / "q3_sales.csv"
        path.write_text(CSV)
        page.get_by_test_id("open-upload").click()
        page.get_by_test_id("upload-input").set_input_files(str(path))
        expect(page.get_by_test_id("dataset-name")).to_have_value("q3 sales")
        page.get_by_test_id("upload-submit").click()
        expect(page.get_by_test_id("toast")).to_contain_text("q3 sales is ready: 4 rows in 1 table")
        expect(page.get_by_test_id("table-q3_sales")).to_be_visible()
        page.get_by_test_id("suggestion").filter(has_text="How many rows").click()
        expect(page.get_by_test_id("metric")).to_contain_text("4")
        page.once("dialog", lambda d: d.accept())
        page.get_by_test_id("delete-dataset").click()
        expect(page.get_by_test_id("dataset-select")).to_have_value("ecommerce")
        expect(page.get_by_test_id("dataset-select").locator("option")).to_have_count(1)

    def test_rejects_non_csv_files(self, page: Page, tmp_path):
        open_app(page)
        path = tmp_path / "notes.pdf"
        path.write_bytes(b"%PDF-1.4")
        page.get_by_test_id("open-upload").click()
        page.get_by_test_id("upload-input").set_input_files(str(path))
        expect(page.get_by_role("alert")).to_contain_text("Only .csv, .tsv and .txt")
        expect(page.get_by_test_id("upload-submit")).to_be_disabled()
        page.keyboard.press("Escape")
        expect(page.get_by_role("dialog")).to_have_count(0)

    def test_server_side_validation_message(self, page: Page, tmp_path):
        open_app(page)
        path = tmp_path / "header_only.csv"
        path.write_text("a,b\n")
        page.get_by_test_id("open-upload").click()
        page.get_by_test_id("upload-input").set_input_files(str(path))
        page.get_by_test_id("upload-submit").click()
        expect(page.get_by_role("alert")).to_contain_text("no data rows")


class TestKeyboardAndTheme:
    def test_command_palette_runs_commands(self, page: Page):
        open_app(page)
        page.keyboard.press("Control+k")
        expect(page.get_by_test_id("palette")).to_be_visible()
        page.get_by_test_id("palette-input").fill("profit")
        page.keyboard.press("Enter")
        expect(page.get_by_test_id("result-title")).to_have_text("Profit margin by category")
        page.keyboard.press("Control+k")
        page.get_by_test_id("palette-input").fill("open dashboard")
        page.keyboard.press("Enter")
        expect(page).to_have_url(re.compile("#/dashboard$"))

    def test_shortcuts(self, page: Page):
        open_app(page)
        page.keyboard.press("/")
        expect(page.get_by_test_id("question-input")).to_be_focused()
        page.get_by_test_id("question-input").press("Escape")
        page.locator("body").click()
        page.keyboard.press("?")
        expect(page.get_by_test_id("shortcuts")).to_be_visible()
        page.keyboard.press("Escape")
        expect(page.get_by_test_id("shortcuts")).to_have_count(0)
        page.keyboard.press("g")
        page.keyboard.press("d")
        expect(page).to_have_url(re.compile("#/dashboard$"))

    def test_theme_persists(self, page: Page):
        open_app(page)
        dark = page.evaluate("document.documentElement.classList.contains('dark')")
        page.get_by_test_id("theme-toggle").click()
        page.reload()
        expect(page.get_by_test_id("welcome")).to_be_visible()
        assert page.evaluate("document.documentElement.classList.contains('dark')") is (not dark)


def test_mobile_layout_has_no_horizontal_scroll(browser, base_url):
    context = browser.new_context(
        base_url=base_url, viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True
    )
    page = context.new_page()
    page.goto("/")
    page.get_by_test_id("suggestion").first.tap()
    expect(page.get_by_test_id("chart-line")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    context.close()


def test_openapi_and_health(page: Page):
    spec = page.request.get("/api/openapi.json").json()
    assert spec["info"]["title"] == "NL2SQL-X API" and "/api/v1/query" in spec["paths"]
    assert page.request.get("/health/ready").json()["status"] == "ok"

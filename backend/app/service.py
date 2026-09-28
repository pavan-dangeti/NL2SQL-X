import asyncio
import re
import secrets
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path

from app import demo_data, ingest
from app.charts import recommend
from app.config import Settings
from app.executor import Executor, QueryExecutionError, QueryResult, QueryTimeoutError
from app.insights import summarize
from app.limits import TTLCache
from app.llm import LLM, SqlDraft, normalise
from app.logs import get_logger
from app.prompts import Turn, system_prompt, user_prompt
from app.schema import Schema, SchemaCache
from app.sql_guard import UnsafeSQLError, check, pretty
from app.store import Store

log = get_logger("service")

Stage = Callable[[str], None]
EDITED = "(edited SQL)"
CHART_TYPES = {"line", "bar", "area", "pie", "metric", "table"}
MAX_PINS = 24


class NotFoundError(Exception):
    pass


class UnanswerableError(Exception):
    pass


class LimitError(Exception):
    pass


def _noop(_: str) -> None:
    return None


class Service:
    def __init__(self, settings: Settings, store: Store, llm: LLM) -> None:
        self.settings = settings
        self.store = store
        self.llm = llm
        self.schemas = SchemaCache()
        self.executor = Executor(settings.max_concurrent_queries, settings.max_result_rows, settings.query_timeout_ms)
        self.cache = TTLCache(settings.cache_size, settings.cache_ttl_s)
        self._inflight: dict[tuple, asyncio.Future] = {}
        self._demo_lock = asyncio.Lock()
        self._demo_day: date | None = None

    @property
    def demo_mode(self) -> bool:
        return self.llm.name == "demo"

    def startup(self) -> None:
        self.settings.datasets_dir.mkdir(parents=True, exist_ok=True)
        demo_path = self.path(demo_data.DEMO_ID)
        demo_data.ensure(demo_path)
        self._demo_day = demo_data.built_on(demo_path)
        schema = self.schemas.get(demo_path)
        self.store.add_dataset(
            id=demo_data.DEMO_ID,
            name=demo_data.DEMO_NAME,
            owner=None,
            tables=sorted(schema.table_names),
            row_count=sum(t.row_count for t in schema.tables),
            size_bytes=demo_path.stat().st_size,
        )
        for dataset_id in self.store.expired_datasets(self.settings.dataset_ttl_days):
            self._remove(dataset_id)

    def path(self, dataset_id: str) -> Path:
        return self.settings.datasets_dir / f"{dataset_id}.db"

    async def _refresh_demo(self) -> None:
        if self._demo_day == date.today():
            return
        async with self._demo_lock:
            if self._demo_day != date.today():
                await asyncio.to_thread(demo_data.ensure, self.path(demo_data.DEMO_ID))
                self._demo_day = date.today()
                self.cache.clear()

    def dataset(self, dataset_id: str, client_id: str) -> dict:
        record = self.store.get_dataset(dataset_id) if re.fullmatch(r"[\w-]{1,64}", dataset_id) else None
        if record is None or (record["owner"] is not None and record["owner"] != client_id):
            raise NotFoundError("Dataset not found.")
        return record

    async def schema(self, dataset_id: str, client_id: str) -> Schema:
        self.dataset(dataset_id, client_id)
        if dataset_id == demo_data.DEMO_ID:
            await self._refresh_demo()
        return await asyncio.to_thread(self.schemas.get, self.path(dataset_id))

    async def ask(
        self, question: str, dataset_id: str, client_id: str, previous: Turn | None = None, stage: Stage = _noop
    ) -> dict:
        started = time.perf_counter()
        stage("schema")
        schema = await self.schema(dataset_id, client_id)
        key = (
            dataset_id,
            self.path(dataset_id).stat().st_mtime,
            normalise(question),
            normalise(previous.sql) if previous else None,
        )
        try:
            cached = self.cache.get(key)
            if cached is not None:
                stage("cache")
                result = {**cached, "cached": True}
            elif key in self._inflight:
                stage("cache")
                result = {**await asyncio.shield(self._inflight[key]), "cached": True}
            else:
                future = asyncio.get_running_loop().create_future()
                self._inflight[key] = future
                try:
                    result = await self._answer(question, dataset_id, schema, previous, stage)
                    future.set_result(result)
                except Exception as exc:
                    future.set_exception(exc)
                    future.exception()
                    raise
                finally:
                    if not future.done():
                        future.cancel()
                    self._inflight.pop(key, None)
                self.cache.set(key, result)
        except Exception as exc:
            await self._log(client_id, dataset_id, question, None, None, "error", str(exc), started)
            raise
        result = {**result, "timings": {**result["timings"], "total_ms": _ms(started)}}
        result["history_id"] = await self._log(
            client_id, dataset_id, question, result["sql"], result["row_count"], "ok", None, started
        )
        stage("done")
        return result

    async def _answer(
        self, question: str, dataset_id: str, schema: Schema, previous: Turn | None, stage: Stage
    ) -> dict:
        system = system_prompt(schema, date.today().isoformat(), dataset_id)
        prompt = user_prompt(question, previous)
        llm_ms = 0.0
        attempts = 0
        while True:
            stage("generating" if attempts == 0 else "repairing")
            t = time.perf_counter()
            draft = await self.llm.draft(system, prompt)
            llm_ms += _ms(t)
            if not draft.answerable or not draft.sql.strip():
                raise UnanswerableError(draft.explanation or "That question cannot be answered from this dataset.")
            try:
                stage("validating")
                checked = check(draft.sql, schema.table_names)
                stage("running")
                result = await self.executor.run(self.path(dataset_id), checked.sql, schema.table_names)
                break
            except (UnsafeSQLError, QueryExecutionError) as exc:
                if attempts >= self.settings.repair_attempts:
                    raise
                attempts += 1
                log.info("repairing_sql", error=str(exc)[:200])
                prompt = user_prompt(question, previous, failed_sql=draft.sql, error=str(exc))
        return self._payload(question, draft, checked.sql, result, llm_ms, repaired=attempts > 0)

    def _payload(
        self, question: str, draft: SqlDraft | None, sql: str, result: QueryResult, llm_ms: float, repaired: bool
    ) -> dict:
        chart = recommend(result.columns, result.rows)
        return {
            "question": question,
            "sql": sql,
            "sql_pretty": pretty(sql),
            "explanation": draft.explanation if draft else None,
            "columns": result.columns,
            "rows": result.rows,
            "row_count": len(result.rows),
            "truncated": result.truncated,
            "chart": chart,
            "insights": summarize(result.columns, result.rows, chart),
            "timings": {"llm_ms": llm_ms, "db_ms": result.duration_ms},
            "model": self.llm.name if draft else None,
            "repaired": repaired,
            "cached": False,
        }

    async def _execute(self, sql: str, dataset_id: str, client_id: str) -> tuple[str, QueryResult]:
        schema = await self.schema(dataset_id, client_id)
        checked = check(sql, schema.table_names)
        return checked.sql, await self.executor.run(self.path(dataset_id), checked.sql, schema.table_names)

    async def run_sql(self, sql: str, dataset_id: str, client_id: str) -> dict:
        started = time.perf_counter()
        try:
            clean, result = await self._execute(sql, dataset_id, client_id)
        except (UnsafeSQLError, QueryExecutionError, QueryTimeoutError) as exc:
            await self._log(client_id, dataset_id, EDITED, sql, None, "error", str(exc), started)
            raise
        payload = self._payload(EDITED, None, clean, result, 0.0, repaired=False)
        payload["timings"]["total_ms"] = _ms(started)
        payload["history_id"] = await self._log(
            client_id, dataset_id, EDITED, clean, payload["row_count"], "ok", None, started
        )
        return payload

    async def preview(self, dataset_id: str, table: str, client_id: str, limit: int) -> dict:
        schema = await self.schema(dataset_id, client_id)
        if table not in schema.table_names:
            raise NotFoundError("Table not found.")
        started = time.perf_counter()
        quoted = '"' + table.replace('"', '""') + '"'
        clean, result = await self._execute(f"SELECT * FROM {quoted} LIMIT {int(limit)}", dataset_id, client_id)
        payload = self._payload(f"Preview of {table}", None, clean, result, 0.0, repaired=False)
        payload["chart"] = {"type": "table", "x": None, "y": []}
        payload["insights"] = []
        payload["timings"]["total_ms"] = _ms(started)
        payload["history_id"] = None
        return payload

    async def _log(self, client_id, dataset_id, question, sql, row_count, status, error, started) -> int | None:
        try:
            return await asyncio.to_thread(
                self.store.log,
                client_id=client_id,
                dataset_id=dataset_id,
                question=question,
                sql=sql,
                row_count=row_count,
                status=status,
                error=error,
                duration_ms=_ms(started),
            )
        except Exception:
            log.exception("history_log_failed")
            return None

    def pins(self, dataset_id: str, client_id: str) -> list[dict]:
        self.dataset(dataset_id, client_id)
        return self.store.pins(client_id, dataset_id)

    async def pin(
        self, *, dataset_id: str, client_id: str, title: str, question: str, sql: str, chart_type: str
    ) -> dict:
        schema = await self.schema(dataset_id, client_id)
        clean = check(sql, schema.table_names).sql
        if self.store.count_pins(client_id) >= MAX_PINS:
            raise LimitError(f"The dashboard holds up to {MAX_PINS} pins. Remove one to add another.")
        return self.store.add_pin(
            id="pin_" + secrets.token_hex(6),
            client_id=client_id,
            dataset_id=dataset_id,
            title=" ".join(title.split())[:120] or question[:120],
            question=question,
            sql=clean,
            chart_type=chart_type if chart_type in CHART_TYPES else "table",
        )

    async def run_pin(self, pin_id: str, client_id: str) -> dict:
        pin = self.store.get_pin(pin_id, client_id)
        if pin is None:
            raise NotFoundError("Pin not found.")
        started = time.perf_counter()
        clean, result = await self._execute(pin["sql"], pin["dataset_id"], client_id)
        payload = self._payload(pin["question"], None, clean, result, 0.0, repaired=False)
        payload["timings"]["total_ms"] = _ms(started)
        payload["history_id"] = None
        return {"pin": pin, "result": payload}

    def rename_pin(self, pin_id: str, client_id: str, title: str) -> None:
        if not self.store.rename_pin(pin_id, client_id, " ".join(title.split())[:120]):
            raise NotFoundError("Pin not found.")

    def unpin(self, pin_id: str, client_id: str) -> None:
        if not self.store.delete_pin(pin_id, client_id):
            raise NotFoundError("Pin not found.")

    async def upload(self, name: str, files: list[tuple[str, bytes]], client_id: str) -> dict:
        if not files:
            raise ingest.IngestError("Add at least one CSV file.")
        if len(files) > 10:
            raise ingest.IngestError("Upload at most 10 files at a time.")
        if self.store.count_owned(client_id) >= self.settings.max_datasets_per_client:
            raise LimitError(
                f"You can keep up to {self.settings.max_datasets_per_client} datasets. Delete one to upload another."
            )
        dataset_id = "ds_" + secrets.token_hex(8)
        path = self.path(dataset_id)
        tables = await asyncio.to_thread(
            ingest.build_dataset, path, files, self.settings.max_upload_rows, self.settings.max_upload_columns
        )
        clean_name = re.sub(r"\s+", " ", name).strip()[:80] or tables[0].name
        record = self.store.add_dataset(
            id=dataset_id,
            name=clean_name,
            owner=client_id,
            tables=[t.name for t in tables],
            row_count=sum(t.rows for t in tables),
            size_bytes=path.stat().st_size,
        )
        log.info("dataset_uploaded", dataset_id=dataset_id, tables=len(tables), rows=record["row_count"])
        return {**record, "builtin": False}

    def delete(self, dataset_id: str, client_id: str) -> None:
        record = self.dataset(dataset_id, client_id)
        if record["owner"] is None:
            raise NotFoundError("Built-in datasets cannot be deleted.")
        self._remove(dataset_id)

    def _remove(self, dataset_id: str) -> None:
        self.store.delete_dataset(dataset_id)
        path = self.path(dataset_id)
        self.schemas.forget(path)
        path.unlink(missing_ok=True)

    async def suggestions(self, dataset_id: str, client_id: str) -> list[str]:
        if dataset_id == demo_data.DEMO_ID:
            self.dataset(dataset_id, client_id)
            return [
                "Revenue by month for the last 12 months",
                "Top 10 products by revenue",
                "Revenue share by region",
                "Average order value by channel",
                "Profit margin by category",
                "Return rate by category",
                "Top 10 customers by lifetime value",
                "Total revenue this year",
            ]
        schema = await self.schema(dataset_id, client_id)
        out = []
        for table in schema.tables[:3]:
            out.append(f"Show the first 20 rows of {table.name}")
            out.append(f"How many rows are in {table.name}")
            if self.demo_mode:
                continue
            labels = [c for c in table.columns if c.values]
            measures = [c for c in table.columns if c.type in {"INTEGER", "REAL"} and not c.primary_key]
            if labels and measures:
                out.append(f"Total {measures[0].name} by {labels[0].name} in {table.name}")
            dates = [c for c in table.columns if c.type in {"DATE", "DATETIME"}]
            if dates:
                out.append(f"Number of {table.name} rows per month by {dates[0].name}")
        return out[:8]


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)

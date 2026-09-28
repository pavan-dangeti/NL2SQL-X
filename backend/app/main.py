import asyncio
import json
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app import __version__
from app.config import Settings, get_settings
from app.executor import QueryExecutionError, QueryTimeoutError
from app.ingest import IngestError
from app.limits import RateLimiter
from app.llm import LLMUnavailableError, create_llm
from app.logs import configure, get_logger, request_id
from app.prompts import Turn
from app.service import LimitError, NotFoundError, Service, UnanswerableError
from app.sql_guard import UnsafeSQLError
from app.store import Store

log = get_logger("api")
CLIENT_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
ERRORS: dict[type[Exception], tuple[int, str]] = {
    NotFoundError: (404, "not_found"),
    UnanswerableError: (422, "unanswerable"),
    UnsafeSQLError: (400, "unsafe_sql"),
    QueryExecutionError: (422, "sql_error"),
    QueryTimeoutError: (422, "timeout"),
    LLMUnavailableError: (503, "llm_unavailable"),
    IngestError: (400, "invalid_file"),
    LimitError: (409, "limit"),
}


class PreviousTurn(BaseModel):
    question: str = Field(max_length=500)
    sql: str = Field(max_length=5000)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    dataset_id: str = Field(default="ecommerce", max_length=64)
    previous: PreviousTurn | None = None

    @field_validator("question")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("Question cannot be empty.")
        return v


class RunSqlRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=5000)
    dataset_id: str = Field(default="ecommerce", max_length=64)


class PinRequest(BaseModel):
    dataset_id: str = Field(max_length=64)
    title: str = Field(default="", max_length=120)
    question: str = Field(min_length=1, max_length=500)
    sql: str = Field(min_length=1, max_length=5000)
    chart_type: Literal["line", "bar", "area", "pie", "metric", "table"] = "table"


class RenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)


def client_ip(request: Request, hops: int) -> str:
    direct = request.client.host if request.client else "unknown"
    if hops <= 0:
        return direct
    chain = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    return chain[-hops] if len(chain) >= hops else direct


def describe(exc: Exception) -> tuple[int, dict]:
    for kind, (status, code) in ERRORS.items():
        if isinstance(exc, kind):
            detail = f"The query could not run: {exc}" if kind is QueryExecutionError else str(exc)
            return status, {"detail": detail, "code": code}
    log.exception("unhandled_error", error=type(exc).__name__)
    return 500, {"detail": "Something went wrong on our side.", "code": "internal"}


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def create_app(settings: Settings | None = None, service: Service | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure(settings.log_level)
    limiter = RateLimiter(settings.rate_limit_per_minute)
    background: set[asyncio.Task] = set()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        svc = service or Service(settings, Store(settings.app_db_path), create_llm(settings))
        await asyncio.to_thread(svc.startup)
        app.state.service = svc
        log.info("started", version=__version__, llm=svc.llm.name, environment=settings.environment)
        yield
        if background:
            await asyncio.wait(background, timeout=10)
        svc.store.close()

    app = FastAPI(
        title="NL2SQL-X API",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-Client-Id", "Accept"],
        expose_headers=["X-Request-Id"],
    )

    @app.middleware("http")
    async def context(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        rid = rid if re.fullmatch(r"[\w-]{1,64}", rid) else uuid.uuid4().hex[:16]
        token = request_id.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id.reset(token)
        response.headers["X-Request-Id"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response

    def svc(request: Request) -> Service:
        return request.app.state.service

    def client(x_client_id: Annotated[str | None, Header()] = None) -> str:
        if not x_client_id or not CLIENT_ID.match(x_client_id):
            raise HTTPException(400, "Missing or invalid X-Client-Id header.")
        return x_client_id

    def throttle(request: Request) -> None:
        wait = limiter.hit(client_ip(request, settings.trusted_proxy_hops))
        if wait is not None:
            raise HTTPException(
                429, f"Too many requests. Try again in {wait:.0f} seconds.", headers={"Retry-After": str(int(wait) + 1)}
            )

    Svc = Annotated[Service, Depends(svc)]
    Client = Annotated[str, Depends(client)]

    @app.exception_handler(Exception)
    async def _errors(_: Request, exc: Exception):
        status, body = describe(exc)
        return JSONResponse(body, status)

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(p) for p in first.get("loc", [])[1:]) or "request"
        message = str(first.get("msg", "Invalid request.")).removeprefix("Value error, ")
        return JSONResponse({"detail": f"{field}: {message}", "code": "invalid_request"}, 422)

    for kind in ERRORS:
        app.add_exception_handler(kind, _errors)

    @app.get("/health/live", include_in_schema=False)
    async def live():
        return {"status": "ok"}

    @app.get("/health/ready", include_in_schema=False)
    def ready(service: Svc):
        service.store.ping()
        return {"status": "ok", "llm": service.llm.name, "version": __version__}

    @app.get("/api/v1/meta")
    async def meta(service: Svc):
        s = service.settings
        return {
            "version": __version__,
            "llm": service.llm.name,
            "demo_mode": service.demo_mode,
            "max_result_rows": s.max_result_rows,
            "max_upload_mb": s.max_upload_mb,
            "query_timeout_ms": s.query_timeout_ms,
        }

    @app.get("/api/v1/datasets")
    def datasets(service: Svc, client_id: Client):
        return [_public(d) for d in service.store.list_datasets(client_id)]

    @app.post("/api/v1/datasets", status_code=201, dependencies=[Depends(throttle)])
    async def upload(
        service: Svc,
        client_id: Client,
        files: Annotated[list[UploadFile], File()],
        name: Annotated[str, Form(max_length=120)] = "",
    ):
        limit = service.settings.max_upload_mb * 1024 * 1024
        payload, total = [], 0
        for f in files:
            if not (f.filename or "").lower().endswith((".csv", ".tsv", ".txt")):
                raise IngestError(f"{f.filename}: only .csv, .tsv or .txt files are supported.")
            data = await f.read(limit - total + 1)
            total += len(data)
            if total > limit:
                raise HTTPException(413, f"Uploads are limited to {service.settings.max_upload_mb} MB.")
            payload.append((f.filename or "data.csv", data))
        return _public(await service.upload(name, payload, client_id))

    @app.delete("/api/v1/datasets/{dataset_id}", status_code=204)
    def delete_dataset(dataset_id: str, service: Svc, client_id: Client):
        service.delete(dataset_id, client_id)
        return Response(status_code=204)

    @app.get("/api/v1/datasets/{dataset_id}/schema")
    async def schema(dataset_id: str, service: Svc, client_id: Client):
        return (await service.schema(dataset_id, client_id)).to_dict()

    @app.get("/api/v1/datasets/{dataset_id}/suggestions")
    async def suggestions(dataset_id: str, service: Svc, client_id: Client):
        return await service.suggestions(dataset_id, client_id)

    @app.get("/api/v1/datasets/{dataset_id}/tables/{table}/preview")
    async def preview(
        dataset_id: str, table: str, service: Svc, client_id: Client, limit: Annotated[int, Query(ge=1, le=200)] = 50
    ):
        return await service.preview(dataset_id, table, client_id, limit)

    @app.post("/api/v1/query", dependencies=[Depends(throttle)])
    async def ask(body: AskRequest, request: Request, service: Svc, client_id: Client):
        previous = Turn(body.previous.question, body.previous.sql) if body.previous else None
        if "text/event-stream" not in request.headers.get("accept", ""):
            return await service.ask(body.question, body.dataset_id, client_id, previous)

        queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()
        task = asyncio.create_task(
            service.ask(
                body.question, body.dataset_id, client_id, previous, stage=lambda s: queue.put_nowait(("stage", s))
            )
        )
        background.add(task)

        def finished(t: asyncio.Task) -> None:
            background.discard(t)
            if t.cancelled():
                queue.put_nowait(
                    ("error", {"detail": "The request was cancelled.", "code": "cancelled", "status": 499})
                )
            elif t.exception() is not None:
                status, body = describe(t.exception())
                queue.put_nowait(("error", {**body, "status": status}))
            else:
                queue.put_nowait(("result", t.result()))

        task.add_done_callback(finished)

        async def events():
            yield ": stream open\n\n"
            while True:
                try:
                    kind, data = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if kind == "stage":
                    yield _sse("stage", {"stage": data})
                    continue
                yield _sse(kind, data)
                return

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/v1/sql", dependencies=[Depends(throttle)])
    async def run_sql(body: RunSqlRequest, service: Svc, client_id: Client):
        return await service.run_sql(body.sql, body.dataset_id, client_id)

    @app.get("/api/v1/history")
    def history(service: Svc, client_id: Client, dataset_id: str = "ecommerce"):
        service.dataset(dataset_id, client_id)
        return service.store.history(client_id, dataset_id)

    @app.delete("/api/v1/history", status_code=204)
    def clear_history(service: Svc, client_id: Client, dataset_id: str = "ecommerce"):
        service.dataset(dataset_id, client_id)
        service.store.clear_history(client_id, dataset_id)
        return Response(status_code=204)

    @app.get("/api/v1/pins")
    def pins(service: Svc, client_id: Client, dataset_id: str = "ecommerce"):
        return service.pins(dataset_id, client_id)

    @app.post("/api/v1/pins", status_code=201)
    async def add_pin(body: PinRequest, service: Svc, client_id: Client):
        return await service.pin(
            dataset_id=body.dataset_id,
            client_id=client_id,
            title=body.title,
            question=body.question,
            sql=body.sql,
            chart_type=body.chart_type,
        )

    @app.post("/api/v1/pins/{pin_id}/run", dependencies=[Depends(throttle)])
    async def run_pin(pin_id: str, service: Svc, client_id: Client):
        return await service.run_pin(pin_id, client_id)

    @app.patch("/api/v1/pins/{pin_id}", status_code=204)
    def rename_pin(pin_id: str, body: RenameRequest, service: Svc, client_id: Client):
        service.rename_pin(pin_id, client_id, body.title)
        return Response(status_code=204)

    @app.delete("/api/v1/pins/{pin_id}", status_code=204)
    def delete_pin(pin_id: str, service: Svc, client_id: Client):
        service.unpin(pin_id, client_id)
        return Response(status_code=204)

    if settings.serve_frontend and (FRONTEND_DIST / "index.html").exists():
        index = FRONTEND_DIST / "index.html"

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            if path.startswith(("api/", "health/")):
                raise HTTPException(404, "Not found.")
            target = (FRONTEND_DIST / path).resolve()
            if path and target.is_file() and FRONTEND_DIST in target.parents:
                headers = (
                    {"Cache-Control": "public, max-age=31536000, immutable"} if path.startswith("assets/") else None
                )
                return FileResponse(target, headers=headers)
            return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app


def _public(dataset: dict) -> dict:
    return {k: v for k, v in dataset.items() if k != "owner"}


app = create_app()

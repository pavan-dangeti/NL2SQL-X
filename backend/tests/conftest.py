import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.llm import DemoLLM, SqlDraft
from app.main import create_app
from app.service import Service
from app.store import Store

CLIENT = {"X-Client-Id": "client-aaaa-1111"}
OTHER = {"X-Client-Id": "client-bbbb-2222"}


class ScriptedLLM:
    """Returns queued drafts in order and records every prompt it received."""

    name = "scripted"

    def __init__(self, *drafts: SqlDraft | Exception) -> None:
        self.queue = list(drafts)
        self.prompts: list[tuple[str, str]] = []

    async def draft(self, system: str, prompt: str) -> SqlDraft:
        self.prompts.append((system, prompt))
        item = self.queue.pop(0) if len(self.queue) > 1 else self.queue[0]
        if isinstance(item, Exception):
            raise item
        return item


def ok(sql: str, explanation: str = "Test answer.") -> SqlDraft:
    return SqlDraft(answerable=True, sql=sql, explanation=explanation)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        environment="test",
        data_dir=tmp_path,
        llm_provider="demo",
        serve_frontend=False,
        rate_limit_per_minute=1000,
        log_level="WARNING",
        _env_file=None,
    )


@pytest.fixture
def make_client(settings):
    clients = []

    def build(llm=None, raise_errors=True, **overrides) -> TestClient:
        s = settings.model_copy(update=overrides)
        service = Service(s, Store(s.app_db_path), llm or DemoLLM())
        client = TestClient(create_app(s, service), raise_server_exceptions=raise_errors)
        client.__enter__()
        clients.append(client)
        return client

    yield build
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()

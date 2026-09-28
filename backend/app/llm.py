import asyncio
import random
import re
from typing import Protocol

from pydantic import BaseModel, Field

from app.config import Settings
from app.logs import get_logger

log = get_logger("llm")


class SqlDraft(BaseModel):
    answerable: bool = Field(description="False when the schema cannot answer the question")
    sql: str = Field(description="A single SQLite SELECT query, or empty when not answerable")
    explanation: str = Field(description="One or two sentences for a business user")


class LLMUnavailableError(Exception):
    def __init__(self, message: str, fallback: bool = False) -> None:
        super().__init__(message)
        self.fallback = fallback


class LLM(Protocol):
    name: str

    async def draft(self, system: str, prompt: str) -> SqlDraft: ...


class GeminiLLM:
    RETRYABLE = frozenset({408, 429, 500, 502, 503, 504})

    def __init__(self, settings: Settings) -> None:
        from google import genai
        from google.genai import types

        self._types = types
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self.models = [settings.gemini_model, *[m for m in [settings.gemini_fallback_model] if m]]
        self.name = f"gemini:{settings.gemini_model}"
        self.timeout = settings.llm_timeout_s
        self.retries = settings.llm_max_retries
        self.thinking = settings.gemini_thinking_level

    def _config(self, system: str, thinking: str | None):
        types = self._types
        return types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.0,
            max_output_tokens=2048,
            response_mime_type="application/json",
            response_schema=SqlDraft,
            thinking_config=types.ThinkingConfig(thinking_level=thinking) if thinking else None,
        )

    async def draft(self, system: str, prompt: str) -> SqlDraft:
        last: LLMUnavailableError | None = None
        for model in dict.fromkeys(self.models):
            try:
                return await self._draft(model, system, prompt)
            except LLMUnavailableError as exc:
                last = exc
                if not exc.fallback:
                    raise
                log.warning("llm_fallback", model=model)
        raise last or LLMUnavailableError("The AI service is unavailable.")

    async def _draft(self, model: str, system: str, prompt: str) -> SqlDraft:
        from google.genai import errors

        thinking = self.thinking
        for attempt in range(self.retries + 1):
            try:
                response = await asyncio.wait_for(
                    self._client.aio.models.generate_content(
                        model=model, contents=prompt, config=self._config(system, thinking)
                    ),
                    timeout=self.timeout,
                )
                parsed = response.parsed
                if isinstance(parsed, SqlDraft):
                    return parsed
                return SqlDraft.model_validate_json(response.text or "")
            except errors.APIError as exc:
                detail = str(getattr(exc, "message", "") or exc)[:300]
                log.warning("llm_api_error", model=model, code=exc.code, attempt=attempt, detail=detail)
                if exc.code == 400 and thinking and "think" in detail.lower():
                    thinking = None
                    continue
                if exc.code in self.RETRYABLE and attempt < self.retries:
                    await asyncio.sleep(_backoff(exc, attempt))
                    continue
                if exc.code == 429:
                    raise LLMUnavailableError(
                        "The Gemini rate limit for this API key was reached. Please wait a minute and try again.",
                        fallback=True,
                    ) from exc
                if exc.code == 404:
                    raise LLMUnavailableError(f"The model {model} is not available.", fallback=True) from exc
                if exc.code in (400, 401, 403):
                    raise LLMUnavailableError(
                        "The AI service rejected the request. Check the API key and model."
                    ) from exc
                raise LLMUnavailableError(
                    "The AI service is busy. Please try again in a moment.", fallback=True
                ) from exc
            except TimeoutError as exc:
                log.warning("llm_timeout", model=model, attempt=attempt)
                if attempt >= self.retries:
                    raise LLMUnavailableError("The AI service timed out. Please try again.", fallback=True) from exc
            except ValueError as exc:
                log.warning("llm_bad_output", model=model, attempt=attempt, error=str(exc)[:200])
                if attempt >= self.retries:
                    raise LLMUnavailableError("The AI service returned an unreadable answer.") from exc
        raise LLMUnavailableError("The AI service is unavailable.", fallback=True)


def _backoff(exc: Exception, attempt: int) -> float:
    match = re.search(r"retry(?:Delay| in)[\"': ]+([\d.]+)s", str(exc), flags=re.IGNORECASE)
    if match:
        return min(float(match.group(1)), 8.0)
    return min(4.0, 0.5 * 2**attempt) + random.random() * 0.25


DEMO_ANSWERS: dict[str, tuple[str, str]] = {
    "revenue by month for the last 12 months": (
        "SELECT strftime('%Y-%m', order_date) AS month, ROUND(SUM(total_amount), 2) AS revenue "
        "FROM orders WHERE status IN ('Delivered', 'Shipped') "
        "AND order_date >= date('now', 'start of month', '-11 months') GROUP BY month ORDER BY month",
        "Monthly revenue from delivered and shipped orders over the last 12 months.",
    ),
    "top 10 products by revenue": (
        "SELECT p.name AS product, p.category, ROUND(SUM(oi.quantity * oi.unit_price * (1 - oi.discount)), 2) "
        "AS revenue FROM order_items oi JOIN orders o ON o.id = oi.order_id JOIN products p ON p.id = oi.product_id "
        "WHERE o.status IN ('Delivered', 'Shipped') GROUP BY p.id ORDER BY revenue DESC LIMIT 10",
        "The ten products that brought in the most revenue, after discounts, from delivered and shipped orders.",
    ),
    "revenue share by region": (
        "SELECT r.name AS region, ROUND(SUM(o.total_amount), 2) AS revenue FROM orders o "
        "JOIN customers c ON c.id = o.customer_id JOIN regions r ON r.id = c.region_id "
        "WHERE o.status IN ('Delivered', 'Shipped') GROUP BY r.id ORDER BY revenue DESC",
        "Revenue from delivered and shipped orders, split by the customer's region.",
    ),
    "average order value by channel": (
        "SELECT channel, ROUND(AVG(total_amount), 2) AS avg_order_value, COUNT(*) AS orders FROM orders "
        "WHERE status IN ('Delivered', 'Shipped') GROUP BY channel ORDER BY avg_order_value DESC",
        "Average order value and order count for each sales channel.",
    ),
    "top 10 customers by lifetime value": (
        "SELECT c.name AS customer, c.segment, COUNT(o.id) AS orders, ROUND(SUM(o.total_amount), 2) AS "
        "lifetime_value FROM customers c JOIN orders o ON o.customer_id = c.id "
        "WHERE o.status IN ('Delivered', 'Shipped') GROUP BY c.id ORDER BY lifetime_value DESC LIMIT 10",
        "The ten customers with the highest spend on delivered and shipped orders.",
    ),
    "return rate by category": (
        "SELECT p.category, ROUND(100.0 * SUM(o.status = 'Returned') / COUNT(*), 2) AS return_rate_pct, "
        "COUNT(*) AS order_lines FROM order_items oi JOIN orders o ON o.id = oi.order_id "
        "JOIN products p ON p.id = oi.product_id GROUP BY p.category ORDER BY return_rate_pct DESC",
        "The share of order lines in each category whose order was returned.",
    ),
    "total revenue this year": (
        "SELECT ROUND(SUM(total_amount), 2) AS revenue FROM orders WHERE status IN ('Delivered', 'Shipped') "
        "AND order_date >= date('now', 'start of year')",
        "Revenue from delivered and shipped orders since 1 January.",
    ),
    "profit margin by category": (
        "SELECT p.category, ROUND(SUM(oi.quantity * (oi.unit_price * (1 - oi.discount) - p.cost)), 2) AS profit, "
        "ROUND(100.0 * SUM(oi.quantity * (oi.unit_price * (1 - oi.discount) - p.cost)) / "
        "SUM(oi.quantity * oi.unit_price * (1 - oi.discount)), 2) AS margin_pct FROM order_items oi "
        "JOIN orders o ON o.id = oi.order_id JOIN products p ON p.id = oi.product_id "
        "WHERE o.status IN ('Delivered', 'Shipped') GROUP BY p.category ORDER BY profit DESC",
        "Profit and margin per category for delivered and shipped orders, after discounts.",
    ),
}


def normalise(question: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", question.lower())).strip()


class DemoLLM:
    """Offline provider for tests, screenshots and keyless demos: answers the sample
    questions exactly and previews uploaded tables."""

    name = "demo"

    async def draft(self, system: str, prompt: str) -> SqlDraft:
        question = normalise(prompt.rsplit("Question:\n", 1)[-1].split("\nYour previous attempt", 1)[0])
        if question in DEMO_ANSWERS:
            sql, explanation = DEMO_ANSWERS[question]
            return SqlDraft(answerable=True, sql=sql, explanation=explanation)
        tables = re.findall(r"^TABLE (\S+)", system, flags=re.MULTILINE)
        match = re.match(r"(?:show|preview) (?:the )?(?:first \d+ rows of |rows of |)(\w+)", question)
        if match and match.group(1) in tables:
            return SqlDraft(
                answerable=True,
                sql=f"SELECT * FROM {match.group(1)} LIMIT 20",
                explanation=f"The first 20 rows of {match.group(1)}.",
            )
        if (match := re.match(r"how many rows are in (\w+)", question)) and match.group(1) in tables:
            return SqlDraft(
                answerable=True,
                sql=f"SELECT COUNT(*) AS row_count FROM {match.group(1)}",
                explanation=f"The number of rows in {match.group(1)}.",
            )
        return SqlDraft(
            answerable=False,
            sql="",
            explanation=("Demo mode only answers the suggested questions. Set GEMINI_API_KEY to ask anything."),
        )


def create_llm(settings: Settings) -> LLM:
    if settings.llm_provider == "demo":
        return DemoLLM()
    if not settings.gemini_api_key:
        log.warning("gemini_key_missing_using_demo")
        return DemoLLM()
    return GeminiLLM(settings)

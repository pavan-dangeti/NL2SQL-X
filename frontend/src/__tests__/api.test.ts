import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, clientId } from "../lib/api";

function stream(chunks: string[]): Response {
  const body = new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(new TextEncoder().encode(c));
      controller.close();
    },
  });
  return new Response(body, { headers: { "content-type": "text/event-stream" } });
}

afterEach(() => vi.unstubAllGlobals());

describe("api client", () => {
  it("keeps a stable client id", () => {
    const id = clientId();
    expect(id).toMatch(/^[A-Za-z0-9_-]{8,64}$/);
    expect(clientId()).toBe(id);
  });

  it("streams stages and resolves with the result across chunk boundaries", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      stream([': open\n\nevent: stage\ndata: {"stage":"schema"}\n\nevent: sta', 'ge\ndata: {"stage":"running"}\n\nevent: result\ndata: {"row_count": 2}\n\n']),
    );
    vi.stubGlobal("fetch", fetchMock);
    const stages: string[] = [];
    const result = await api.ask("q", "ecommerce", null, (s) => stages.push(s));
    expect(stages).toEqual(["schema", "running"]);
    expect(result.row_count).toBe(2);
    const [, init] = fetchMock.mock.calls[0];
    expect(new Headers(init.headers).get("X-Client-Id")).toBe(clientId());
    expect(new Headers(init.headers).get("Accept")).toBe("text/event-stream");
  });

  it("turns streamed errors into ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(stream(['event: error\ndata: {"detail":"busy","code":"llm_unavailable","status":503}\n\n'])));
    const err = await api.ask("q", "ecommerce", null, () => undefined).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ message: "busy", status: 503, code: "llm_unavailable", retriable: true });
  });

  it("reports a stream that ends early", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(stream(['event: stage\ndata: {"stage":"schema"}\n\n'])));
    await expect(api.ask("q", "d", null, () => undefined)).rejects.toMatchObject({ code: "network" });
  });

  it("falls back to JSON responses and readable errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Dataset not found.", code: "not_found" }), { status: 404 })));
    await expect(api.ask("q", "d", null, () => undefined)).rejects.toMatchObject({ message: "Dataset not found.", retriable: false });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>bad gateway</html>", { status: 502 })));
    await expect(api.datasets()).rejects.toMatchObject({ message: "The server had a problem. Please try again.", status: 502 });
  });

  it("maps network failures and passes aborts through", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(api.meta()).rejects.toMatchObject({ status: 0, code: "network" });
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new DOMException("aborted", "AbortError")));
    await expect(api.meta()).rejects.toMatchObject({ name: "AbortError" });
  });

  it("returns undefined for 204 and sends form data untouched", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(api.unpin("pin_1")).resolves.toBeUndefined();
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ id: "ds_1" }), { status: 201 }));
    await api.upload("Sales", [new File(["a,b\n1,2"], "s.csv")]);
    const init = fetchMock.mock.calls[1][1];
    expect(init.body).toBeInstanceOf(FormData);
    expect(new Headers(init.headers).has("Content-Type")).toBe(false);
  });
});

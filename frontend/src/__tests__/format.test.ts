import { describe, expect, it } from "vitest";
import { parseEvents } from "../lib/api";
import { formatBytes, formatCell, formatCompact, formatMs, humanize, relativeTime, sortRows, toCsv, tokenizeSql } from "../lib/format";

describe("formatting", () => {
  it("formats cells", () => {
    expect(formatCell(null)).toBe("—");
    expect(formatCell(2026)).toBe("2026");
    expect(formatCell(1234567.891)).toBe("1,234,567.89");
    expect(formatCell("text")).toBe("text");
  });

  it("formats compact numbers, durations and sizes", () => {
    expect(formatCompact(125000)).toBe("125K");
    expect(formatCompact(950.5)).toBe("950.5");
    expect(formatMs(840.4)).toBe("840 ms");
    expect(formatMs(2300)).toBe("2.3 s");
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2 KB");
    expect(formatBytes(3 * 1024 * 1024)).toBe("3.0 MB");
  });

  it("humanizes column names", () => {
    expect(humanize("avg_order_value")).toBe("Avg order value");
  });

  it("describes relative time", () => {
    const now = new Date("2026-09-27T12:00:00Z");
    expect(relativeTime("2026-09-27T11:59:50Z", now)).toBe("just now");
    expect(relativeTime("2026-09-27T11:30:00Z", now)).toBe("30 min ago");
    expect(relativeTime("2026-09-27T09:00:00Z", now)).toBe("3 h ago");
    expect(relativeTime("not a date", now)).toBe("");
  });
});

describe("csv export", () => {
  it("escapes quotes, commas and newlines", () => {
    expect(toCsv(["a", "b"], [["x,y", 'say "hi"'], [null, 3]])).toBe('a,b\r\n"x,y","say ""hi"""\r\n,3');
  });

  it("neutralises spreadsheet formulas", () => {
    expect(toCsv(["f"], [["=HYPERLINK(1)"], ["-5"], [-5]])).toBe("f\r\n'=HYPERLINK(1)\r\n'-5\r\n-5");
  });
});

describe("sorting", () => {
  const rows = [["b", 2], [null, 1], ["a", 10], ["a2", null]];
  it("sorts numbers and text with nulls last", () => {
    expect(sortRows(rows, 1, "desc").map((r) => r[1])).toEqual([10, 2, 1, null]);
    expect(sortRows(rows, 1, "asc").map((r) => r[1])).toEqual([1, 2, 10, null]);
    expect(sortRows(rows, 0, "asc").map((r) => r[0])).toEqual(["a", "a2", "b", null]);
  });

  it("is stable and does not mutate input", () => {
    const input = [["x", 1], ["y", 1]];
    expect(sortRows(input, 1, "asc")).toEqual(input);
    expect(input).toEqual([["x", 1], ["y", 1]]);
  });
});

describe("sql tokenizer", () => {
  it("round-trips every character", () => {
    const sql = "SELECT name, 'it''s' AS t, 3.5 -- note\nFROM x WHERE a <> 'b";
    expect(tokenizeSql(sql).map((t) => t.text).join("")).toBe(sql);
  });

  it("classifies tokens", () => {
    const kinds = Object.fromEntries(tokenizeSql("select 'a' 42 foo -- c").map((t) => [t.text, t.kind]));
    expect(kinds).toMatchObject({ select: "keyword", "'a'": "string", "42": "number", foo: "plain", "-- c": "comment" });
  });
});

describe("server-sent events parser", () => {
  it("parses complete events and keeps the remainder", () => {
    const { events, rest } = parseEvents(': open\n\nevent: stage\ndata: {"stage":"schema"}\n\nevent: result\ndata: {"a"');
    expect(events).toEqual([{ event: "stage", data: '{"stage":"schema"}' }]);
    expect(rest).toBe('event: result\ndata: {"a"');
  });

  it("handles CRLF and multi-line data", () => {
    const { events } = parseEvents("event: x\r\ndata: a\r\ndata: b\r\n\r\n");
    expect(events).toEqual([{ event: "x", data: "a\nb" }]);
  });
});

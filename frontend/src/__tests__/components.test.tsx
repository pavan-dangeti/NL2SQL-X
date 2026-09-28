import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRef } from "react";
import { describe, expect, it, vi } from "vitest";
import { CommandPalette } from "../components/CommandPalette";
import { Composer, type ComposerHandle } from "../components/Composer";
import { DataTable } from "../components/DataTable";
import { ResultView } from "../components/ResultView";
import { Toaster } from "../components/Toaster";
import { plotOptions } from "../components/Visual";
import type { QueryResult } from "../lib/types";

function result(overrides: Partial<QueryResult> = {}): QueryResult {
  return {
    question: "Revenue by region",
    sql: "SELECT region, revenue FROM t",
    sql_pretty: "SELECT\n  region,\n  revenue\nFROM t",
    explanation: "Revenue per region.",
    columns: ["region", "revenue"],
    rows: [["EU", 10], ["US", 30], ["IN", 5]],
    row_count: 3,
    truncated: false,
    chart: { type: "table", x: "region", y: ["revenue"] },
    insights: ["US leads with 30 (66.7% of the total revenue)."],
    timings: { llm_ms: 400, db_ms: 3, total_ms: 410 },
    model: "demo",
    repaired: false,
    cached: false,
    history_id: 1,
    ...overrides,
  };
}

describe("DataTable", () => {
  const rows = Array.from({ length: 120 }, (_, i) => [`item ${i}`, i]);

  it("paginates, sorts and filters", async () => {
    const user = userEvent.setup();
    render(<DataTable columns={["name", "units"]} rows={rows} />);
    expect(screen.getByTestId("table-range")).toHaveTextContent("Rows 1–50 of 120");
    await user.click(screen.getByTestId("next-page"));
    expect(screen.getByTestId("table-range")).toHaveTextContent("Rows 51–100 of 120");
    await user.click(screen.getByRole("button", { name: /Units/ }));
    expect(screen.getAllByRole("row")[1]).toHaveTextContent("item 119");
    await user.type(screen.getByTestId("table-filter"), "item 7");
    expect(screen.getAllByRole("row")).toHaveLength(12);
  });

  it("shows empty and no-match states", async () => {
    const { rerender } = render(<DataTable columns={["a"]} rows={[]} />);
    expect(screen.getByText(/returned no rows/)).toBeInTheDocument();
    rerender(<DataTable columns={["name", "units"]} rows={rows} />);
    await userEvent.type(screen.getByTestId("table-filter"), "zzz");
    expect(screen.getByText(/No rows match/)).toBeInTheDocument();
  });

  it("renders nulls and right-aligns numbers", () => {
    render(<DataTable columns={["name", "units"]} rows={[["a", null], [null, 3]]} />);
    const cells = screen.getAllByRole("cell");
    expect(cells[1]).toHaveTextContent("—");
    expect(cells[3]).toHaveClass("text-right");
  });
});

describe("Composer", () => {
  function setup(busy = false) {
    const onAsk = vi.fn();
    const onCancel = vi.fn();
    const ref = createRef<ComposerHandle>();
    render(
      <Composer ref={ref} busy={busy} suggestions={["Top products"]} canFollowUp followUp={false} onFollowUpChange={() => undefined} onAsk={onAsk} onCancel={onCancel} />,
    );
    return { onAsk, onCancel, ref };
  }

  it("asks on Enter, keeps Shift+Enter as a newline and trims", async () => {
    const { onAsk } = setup();
    const input = screen.getByTestId("question-input");
    await userEvent.type(input, "  hello{Shift>}{Enter}{/Shift}world  {Enter}");
    expect(onAsk).toHaveBeenCalledWith("hello\nworld");
  });

  it("ignores empty questions and runs suggestions", async () => {
    const { onAsk } = setup();
    expect(screen.getByTestId("ask")).toBeDisabled();
    await userEvent.click(screen.getByTestId("suggestion"));
    expect(onAsk).toHaveBeenCalledWith("Top products");
  });

  it("shows stop while busy", async () => {
    const { onCancel } = setup(true);
    await userEvent.click(screen.getByTestId("cancel"));
    expect(onCancel).toHaveBeenCalled();
    expect(screen.queryByTestId("suggestion")).toBeNull();
  });

  it("inserts schema names at the cursor", async () => {
    const { ref } = setup();
    const input = screen.getByTestId("question-input") as HTMLTextAreaElement;
    await userEvent.type(input, "total by");
    act(() => ref.current?.insert("region"));
    expect(input.value).toBe("total by region ");
  });
});

describe("CommandPalette", () => {
  it("filters, navigates with arrows and runs the selection", async () => {
    const a = vi.fn();
    const b = vi.fn();
    const onClose = vi.fn();
    render(
      <CommandPalette
        onClose={onClose}
        commands={[
          { id: "a", group: "Go", label: "Open dashboard", icon: null, run: a },
          { id: "b", group: "Go", label: "Ask a question", icon: null, run: b },
        ]}
      />,
    );
    await userEvent.keyboard("{ArrowDown}{Enter}");
    expect(b).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it("shows an empty state", async () => {
    render(<CommandPalette onClose={() => undefined} commands={[{ id: "a", group: "Go", label: "Dashboard", icon: null, run: () => undefined }]} />);
    await userEvent.type(screen.getByTestId("palette-input"), "nothing here");
    expect(screen.getByText("No commands match.")).toBeInTheDocument();
  });
});

describe("ResultView", () => {
  function show(r: QueryResult, onPin = vi.fn().mockResolvedValue(undefined)) {
    render(
      <Toaster>
        <ResultView result={r} busy={false} canShare onRunSql={vi.fn()} onPin={onPin} onShare={vi.fn()} />
      </Toaster>,
    );
    return onPin;
  }

  it("shows explanation, insights and stats", () => {
    show(result({ cached: true, repaired: true, truncated: true }));
    expect(screen.getByTestId("explanation")).toHaveTextContent("Revenue per region.");
    expect(screen.getByTestId("insights")).toHaveTextContent("US leads");
    const stats = screen.getByTestId("result-stats");
    for (const text of ["3 rows", "410 ms", "cached", "self-corrected", "first 3 rows shown"]) expect(stats).toHaveTextContent(text);
  });

  it("switches to SQL and back to the table", async () => {
    show(result());
    await userEvent.click(screen.getByTestId("view-sql"));
    expect(screen.getByTestId("sql-code")).toHaveTextContent("FROM t");
    await userEvent.click(screen.getByTestId("view-table"));
    expect(within(screen.getByTestId("results-table")).getAllByRole("row")).toHaveLength(4);
  });

  it("pins with the selected view", async () => {
    const onPin = show(result());
    await userEvent.click(screen.getByTestId("view-sql"));
    await userEvent.click(screen.getByTestId("pin"));
    expect(onPin).toHaveBeenCalledWith("table");
  });

  it("offers the right views for the result shape", () => {
    expect(plotOptions(result({ chart: { type: "metric", x: null, y: ["revenue"] } }))).toEqual(["metric", "table"]);
    expect(plotOptions(result({ chart: { type: "bar", x: "region", y: ["revenue"] } }))).toEqual(["bar", "line", "area", "pie", "table"]);
    expect(plotOptions(result({ chart: { type: "table", x: null, y: [] } }))).toEqual(["table"]);
  });
});

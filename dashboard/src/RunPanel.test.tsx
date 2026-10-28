import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { Run } from "./api";
import { RunPanel } from "./RunPanel";
import { mockApi, type Routes } from "./testing";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const run: Run = {
  run_id: "run-1",
  max_claims: 3,
  status: "running",
  todos: [
    { task: "Work CLM-1001", status: "done" },
    { task: "Work CLM-1002", status: "in_progress" },
    { task: "Work CLM-1003", status: "to_do" },
    { task: "Work CLM-1004", status: "for_handler" },
  ],
  summary: null,
  problem: null,
  started_at: "2026-10-28T09:30:00+00:00",
  finished_at: null,
};

function capField(): HTMLInputElement {
  return screen.getByLabelText<HTMLInputElement>(/Claims to work/);
}

it("says when the agent has not run yet", async () => {
  mockApi({ "/api/runs/latest": null });
  render(<RunPanel waiting={25} />);
  expect(
    await screen.findByText("The agent has not run on the queue yet."),
  ).toBeDefined();
});

it("starts a run with the cap entered", async () => {
  const api: Routes = {
    "/api/runs/latest": null,
    "POST /api/runs": { ...run, todos: [] },
  };
  const fetchMock = mockApi(api);
  render(<RunPanel waiting={25} />);
  expect(capField().value).toBe("5");
  fireEvent.change(capField(), { target: { value: "3" } });
  api["/api/runs/latest"] = { ...run, todos: [] };
  fireEvent.click(screen.getByRole("button", { name: "Start run" }));
  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/runs",
      expect.objectContaining({ body: '{"max_claims":3}' }),
    );
  });
  expect(
    await screen.findByText("The agent has not written its list yet."),
  ).toBeDefined();
  expect(
    screen.getByRole("button", { name: "Start run" }).hasAttribute("disabled"),
  ).toBe(true);
});

it("fills in the whole queue", () => {
  mockApi({ "/api/runs/latest": null });
  render(<RunPanel waiting={22} />);
  fireEvent.click(screen.getByRole("button", { name: "Whole queue" }));
  expect(capField().value).toBe("22");
});

it("shows the to-do list with each item's state", async () => {
  mockApi({ "/api/runs/latest": run });
  render(<RunPanel waiting={21} />);
  expect(await screen.findByText("Work CLM-1001")).toBeDefined();
  expect(screen.getByText("Done")).toBeDefined();
  expect(screen.getByText("In progress")).toBeDefined();
  expect(screen.getByText("To do")).toBeDefined();
  expect(screen.getByText("Left for a handler")).toBeDefined();
  expect(screen.getByText("(2 of 4 finished)")).toBeDefined();
  expect(screen.getByText(/Running, up to 3 claims/)).toBeDefined();
  expect(screen.getByText("2026-10-28 09:30 UTC")).toBeDefined();
});

it("shows the summary of a finished run", async () => {
  mockApi({
    "/api/runs/latest": {
      ...run,
      max_claims: 1,
      status: "finished",
      todos: [{ task: "Work CLM-1001", status: "done" }],
      summary: "One claim approved, $420.00 paid.",
    },
  });
  render(<RunPanel waiting={24} />);
  expect(
    await screen.findByText("One claim approved, $420.00 paid."),
  ).toBeDefined();
  expect(screen.getByText(/Finished, up to 1 claim,/)).toBeDefined();
});

it("shows why a run stopped, and a refused start", async () => {
  mockApi({
    "/api/runs/latest": {
      ...run,
      status: "stopped",
      problem: "The backend restarted during the run.",
    },
  });
  render(<RunPanel waiting={0} />);
  expect(
    await screen.findByText("The backend restarted during the run."),
  ).toBeDefined();
  expect(
    screen
      .getByRole("button", { name: "Whole queue" })
      .hasAttribute("disabled"),
  ).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Start run" }));
  expect(await screen.findByText(/No route POST \/api\/runs/)).toBeDefined();
});

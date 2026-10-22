import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { App } from "./App";
import { claims, mockApi } from "./testing";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.location.hash = "";
});

it("shows the queue with counts by state", async () => {
  mockApi({ "/api/claims": claims });
  render(<App />);
  expect(await screen.findByText("Maya Patel")).toBeDefined();
  const tiles = screen.getByLabelText("Claims by state");
  expect(within(tiles).getByText("Waiting").previousSibling).toBeDefined();
  expect(tiles.textContent).toContain("1Waiting");
  expect(tiles.textContent).toContain("0In progress");
  expect(tiles.textContent).toContain("1Decided");
  expect(screen.getByText("$1,250.00")).toBeDefined();
  expect(screen.getByText("Trip delay")).toBeDefined();
  expect(screen.getByText("Approve")).toBeDefined();
  expect(
    screen.getByRole("link", { name: "CLM-1002" }).getAttribute("href"),
  ).toBe("#/claims/CLM-1002");
});

it("says when the queue cannot load", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
  render(<App />);
  expect(await screen.findByText(/Could not load the queue/)).toBeDefined();
});

it("shows the agent's instructions, read only", async () => {
  mockApi({ "/api/instructions": { instructions: "You are the agent." } });
  window.location.hash = "#/instructions";
  render(<App />);
  expect(await screen.findByText("You are the agent.")).toBeDefined();
  expect(screen.queryByRole("textbox")).toBeNull();
  expect(screen.queryByRole("button")).toBeNull();
});

it("says when the instructions cannot load", async () => {
  mockApi({});
  window.location.hash = "#/instructions";
  render(<App />);
  expect(
    await screen.findByText(/Could not load the instructions: Error: No route/),
  ).toBeDefined();
});

it("follows the hash", async () => {
  mockApi({
    "/api/claims": claims,
    "/api/instructions": { instructions: "Hi" },
  });
  render(<App />);
  expect(await screen.findByText("Maya Patel")).toBeDefined();
  window.location.hash = "#/instructions";
  window.dispatchEvent(new HashChangeEvent("hashchange"));
  expect(await screen.findByText("Hi")).toBeDefined();
});

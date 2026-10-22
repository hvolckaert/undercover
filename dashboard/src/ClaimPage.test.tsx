import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { Claim, Step } from "./api";
import { ClaimPage } from "./ClaimPage";
import { mockApi, type Routes } from "./testing";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const waiting: Claim = {
  claim_id: "CLM-1001",
  policy_id: "POL-2001",
  customer_id: "CUS-3001",
  claim_type: "trip_delay",
  submitted_on: "2026-06-24",
  incident_date: "2026-06-18",
  incident_location: "Rome, Italy",
  summary: "Flight home canceled",
  story: "My flight home from Rome was canceled.",
  items: [{ description: "Airport hotel", category: "hotel", amount: 245 }],
  amount_claimed: 245,
  documents: [
    { name: "Hotel receipt", type: "receipt", content: "Total $245.00" },
  ],
  status: "waiting",
  decision: null,
  sign_off: null,
  payment: null,
};

const approved = (payout: number) => ({
  decision: "approve" as const,
  payout,
  calculation: `Hotel ${String(payout)}`,
  reason: "The flight was canceled for a crew problem.",
  policy_section: "3. Trip Delay",
});

const step = (step_id: number, kind: Step["kind"], content: string): Step => ({
  step_id,
  kind,
  content,
  created_at: "2026-10-22T07:00:00+00:00",
});

function routes(claim: Claim, steps: Step[] = []): Routes {
  return {
    "/api/claims/CLM-1001": claim,
    "/api/claims/CLM-1001/steps": steps,
    "/api/policies/POL-2001": {
      policy_id: "POL-2001",
      plan: "premium",
      purchased_on: "2026-04-22",
      trip: {
        destination: "Rome, Italy",
        departs_on: "2026-06-10",
        returns_on: "2026-06-18",
        trip_cost: 3100,
      },
      travelers: ["Maya Patel"],
      plan_details: { name: "UnderCover Premium", deductible: 50 },
      add_on_details: [],
    },
    "/api/customers/CUS-3001": {
      customer_id: "CUS-3001",
      name: "Maya Patel",
      customer_since: "2023-04-11",
      previous_claims: [
        {
          claim_id: "CLM-0412",
          filed_on: "2024-08-19",
          claim_type: "baggage_delay",
          summary: "Bag arrived late",
          outcome: "approved",
          amount_paid: 140,
        },
      ],
    },
    "/api/handlers": [
      { handler_id: "HND-01", name: "Dana Whitfield", role: "Senior" },
    ],
  };
}

it("shows a waiting claim in full", async () => {
  mockApi(routes(waiting));
  render(<ClaimPage claimId="CLM-1001" />);
  expect(await screen.findByText(waiting.story)).toBeDefined();
  expect(screen.getByText("Hotel receipt")).toBeDefined();
  expect(screen.getAllByText("$245.00").length).toBeGreaterThan(0);
  expect(
    screen.getByText("The agent has not decided this claim yet."),
  ).toBeDefined();
  expect(screen.getByText("No steps yet.")).toBeDefined();
  expect(await screen.findByText("UnderCover Premium")).toBeDefined();
  expect(await screen.findByText(/Bag arrived late/)).toBeDefined();
});

it("runs the agent and shows its steps as they land", async () => {
  const api = routes(waiting);
  api["POST /api/claims/CLM-1001/run"] = { status: "in_progress" };
  const fetchMock = mockApi(api);
  render(<ClaimPage claimId="CLM-1001" />);
  api["/api/claims/CLM-1001"] = { ...waiting, status: "in_progress" };
  fireEvent.click(await screen.findByRole("button", { name: "Run the agent" }));
  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/claims/CLM-1001/run",
      expect.objectContaining({ method: "POST" }),
    );
  });
  expect(await screen.findByText("In progress")).toBeDefined();

  api["/api/claims/CLM-1001/steps"] = [
    step(1, "tool_call", 'get_claim {"claim_id": "CLM-1001"}'),
  ];
  expect(
    await screen.findByText(
      'get_claim {"claim_id": "CLM-1001"}',
      {},
      { timeout: 3000 },
    ),
  ).toBeDefined();

  api["/api/claims/CLM-1001"] = {
    ...waiting,
    status: "decided",
    decision: approved(245),
    payment: { amount: 245, paid_at: "2026-10-22T07:01:00+00:00" },
  };
  api["/api/claims/CLM-1001/steps"] = [
    step(1, "tool_call", 'get_claim {"claim_id": "CLM-1001"}'),
    step(2, "tool_result", `get_claim: ${"x".repeat(300)}`),
    step(3, "reply", "Approved for $245.00."),
  ];
  expect(
    await screen.findByText("Approved for $245.00.", {}, { timeout: 3000 }),
  ).toBeDefined();
  expect(screen.getByText("Decision: Approve")).toBeDefined();
  expect(screen.getByText("3. Trip Delay")).toBeDefined();
  expect(screen.getByText("$245.00 paid")).toBeDefined();
  expect(screen.queryByRole("button", { name: "Run the agent" })).toBeNull();
});

it("says when the agent cannot start", async () => {
  mockApi(routes(waiting));
  render(<ClaimPage claimId="CLM-1001" />);
  fireEvent.click(await screen.findByRole("button", { name: "Run the agent" }));
  expect(await screen.findByText(/No route POST/)).toBeDefined();
});

it("holds a large payout until a handler signs off", async () => {
  const held = { ...waiting, status: "waiting_for_signoff" as const };
  const api = routes({ ...held, decision: approved(1250) }, [
    step(1, "reply", "Approved, awaiting sign-off."),
  ]);
  api["POST /api/claims/CLM-1001/sign-off"] = { status: "decided" };
  const fetchMock = mockApi(api);
  render(<ClaimPage claimId="CLM-1001" />);
  expect(await screen.findByText("Held for sign-off")).toBeDefined();
  const button = screen.getByRole("button", { name: "Sign off and pay" });
  expect(button.hasAttribute("disabled")).toBe(true);

  await screen.findByRole("option", { name: "Dana Whitfield" });
  fireEvent.change(screen.getByLabelText(/Handler/), {
    target: { value: "HND-01" },
  });
  api["/api/claims/CLM-1001"] = {
    ...waiting,
    status: "decided",
    decision: approved(1250),
    sign_off: { handler_id: "HND-01", name: "Dana Whitfield", at: "now" },
    payment: { amount: 1250, paid_at: "now" },
  };
  fireEvent.click(button);
  expect(await screen.findByText("$1,250.00 paid")).toBeDefined();
  expect(screen.getByText("Dana Whitfield")).toBeDefined();
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/claims/CLM-1001/sign-off",
    expect.objectContaining({ body: '{"handler_id":"HND-01"}' }),
  );
});

it("says when the sign-off is refused", async () => {
  mockApi(
    routes(
      { ...waiting, status: "waiting_for_signoff", decision: approved(1250) },
      [step(1, "reply", "Done.")],
    ),
  );
  render(<ClaimPage claimId="CLM-1001" />);
  await screen.findByRole("option", { name: "Dana Whitfield" });
  fireEvent.change(screen.getByLabelText(/Handler/), {
    target: { value: "HND-01" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Sign off and pay" }));
  expect(await screen.findByText(/No route POST/)).toBeDefined();
});

it("shows a declined claim and a problem step", async () => {
  mockApi(
    routes(
      {
        ...waiting,
        status: "decided",
        decision: { ...approved(0), decision: "decline" },
      },
      [step(1, "error", "The agent stopped with an error.")],
    ),
  );
  render(<ClaimPage claimId="CLM-1001" />);
  expect(await screen.findByText("Decision: Decline")).toBeDefined();
  expect(screen.getByText("None")).toBeDefined();
  expect(screen.getByText("Problem")).toBeDefined();
});

it("says when the claim cannot load", async () => {
  mockApi({});
  render(<ClaimPage claimId="CLM-1001" />);
  expect(await screen.findByText(/Could not load the claim/)).toBeDefined();
});

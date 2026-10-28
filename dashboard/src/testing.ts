import { vi } from "vitest";
import type { ClaimSummary } from "./api";

export const claims: ClaimSummary[] = [
  {
    claim_id: "CLM-1001",
    customer_name: "Maya Patel",
    claim_type: "trip_delay",
    summary: "Flight home canceled",
    submitted_on: "2026-06-24",
    amount_claimed: 420,
    status: "decided",
    attempts: 1,
    decision: "approve",
    payout: 420,
  },
  {
    claim_id: "CLM-1002",
    customer_name: "Ben Ortiz",
    claim_type: "baggage",
    summary: "Suitcase lost",
    submitted_on: "2026-06-25",
    amount_claimed: 1250,
    status: "waiting",
    attempts: 0,
    decision: null,
    payout: null,
  },
];

export type Routes = Record<string, unknown>;

export function mockApi(routes: Routes) {
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    const path = init?.method === "POST" ? `POST ${url}` : url;
    if (!(path in routes)) {
      return Promise.resolve(
        new Response(JSON.stringify({ detail: `No route ${path}` }), {
          status: 404,
        }),
      );
    }
    return Promise.resolve(new Response(JSON.stringify(routes[path])));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

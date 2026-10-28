export type Status =
  | "waiting"
  | "in_progress"
  | "waiting_for_signoff"
  | "decided"
  | "needs_handler";
export type Outcome = "approve" | "decline" | "refer";

export interface ClaimSummary {
  claim_id: string;
  customer_name: string;
  claim_type: string;
  summary: string;
  submitted_on: string;
  amount_claimed: number;
  status: Status;
  attempts: number;
  decision: Outcome | null;
  payout: number | null;
}

export interface Item {
  description: string;
  category: string;
  amount: number;
}

export interface Document {
  name: string;
  type: string;
  content: string;
}

export interface Decision {
  decision: Outcome;
  payout: number;
  calculation: string;
  reason: string;
  policy_section: string;
}

export interface SignOff {
  handler_id: string;
  name: string;
  at: string;
}

export interface Payment {
  amount: number;
  paid_at: string;
}

export interface Claim {
  claim_id: string;
  policy_id: string;
  customer_id: string;
  claim_type: string;
  submitted_on: string;
  incident_date: string;
  incident_location: string;
  summary: string;
  story: string;
  items: Item[];
  amount_claimed: number;
  documents: Document[];
  status: Status;
  attempts: number;
  decision: Decision | null;
  sign_off: SignOff | null;
  payment: Payment | null;
}

export interface Plan {
  name: string;
  deductible: number;
}

export interface AddOn {
  add_on: string;
  name: string;
  effect: string;
}

export interface Policy {
  policy_id: string;
  plan: string;
  purchased_on: string;
  trip: {
    destination: string;
    departs_on: string;
    returns_on: string;
    trip_cost: number;
  };
  travelers: string[];
  plan_details: Plan;
  add_on_details: AddOn[];
}

export interface PreviousClaim {
  claim_id: string;
  filed_on: string;
  claim_type: string;
  summary: string;
  outcome: string;
  amount_paid: number;
}

export interface Customer {
  customer_id: string;
  name: string;
  customer_since: string;
  previous_claims: PreviousClaim[];
}

export interface Step {
  step_id: number;
  thread_id: string;
  kind: "tool_call" | "tool_result" | "reply" | "error";
  content: string;
  created_at: string;
}

export type TodoStatus = "to_do" | "in_progress" | "done" | "for_handler";

export interface Todo {
  task: string;
  status: TodoStatus;
}

export interface Run {
  run_id: string;
  max_claims: number;
  status: "running" | "finished" | "stopped";
  todos: Todo[];
  summary: string | null;
  problem: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface Section {
  document: "policy_wording" | "claims_manual";
  section: string;
  title: string;
  text: string;
}

export interface Instructions {
  queue: string;
  claim: string;
}

export interface Handler {
  handler_id: string;
  name: string;
  role: string;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    const body = (await response.json()) as { detail?: unknown };
    throw new Error(
      typeof body.detail === "string" ? body.detail : response.statusText,
    );
  }
  return (await response.json()) as T;
}

export function getJson<T>(path: string): Promise<T> {
  return request<T>(path);
}

export function postJson<T>(path: string, body?: object): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

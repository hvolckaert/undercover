import { useState } from "react";
import {
  postJson,
  type Claim,
  type Customer,
  type Handler,
  type Policy,
  type Step,
} from "./api";
import { label, money } from "./format";
import { useResource } from "./useResource";

const STEP_LABELS: Record<Step["kind"], string> = {
  tool_call: "Called",
  tool_result: "Result",
  reply: "Reply",
  error: "Problem",
};

function paymentText(claim: Claim): string {
  if (claim.payment) return `${money(claim.payment.amount)} paid`;
  if (claim.status === "waiting_for_signoff") return "Held for sign-off";
  return claim.decision?.decision === "approve" ? "Not paid" : "None";
}

export function DecisionPanel({ claim }: Readonly<{ claim: Claim }>) {
  const { decision, sign_off } = claim;
  if (!decision) {
    return (
      <section className="panel">
        <h2>Decision</h2>
        <p className="muted">The agent has not decided this claim yet.</p>
      </section>
    );
  }
  return (
    <section className="panel">
      <h2>Decision: {label(decision.decision)}</h2>
      <dl className="facts">
        <dt>Payout</dt>
        <dd className="mono">{money(decision.payout)}</dd>
        <dt>Policy section</dt>
        <dd>{decision.policy_section}</dd>
        <dt>Payment</dt>
        <dd>{paymentText(claim)}</dd>
        {sign_off && (
          <>
            <dt>Signed off by</dt>
            <dd>{sign_off.name}</dd>
          </>
        )}
      </dl>
      <h3>Reason</h3>
      <p>{decision.reason}</p>
      <h3>Calculation</h3>
      <p>{decision.calculation}</p>
    </section>
  );
}

export function SignOffPanel({
  claim,
  onDone,
}: Readonly<{ claim: Claim; onDone: () => void }>) {
  const { data: handlers } = useResource<Handler[]>("/api/handlers");
  const [handlerId, setHandlerId] = useState("");
  const [error, setError] = useState<string>();
  const payout = claim.decision?.payout ?? 0;

  const signOff = () => {
    postJson(`/api/claims/${claim.claim_id}/sign-off`, {
      handler_id: handlerId,
    }).then(onDone, (reason: unknown) => {
      setError(String(reason));
    });
  };

  return (
    <section className="panel">
      <h2>Waiting for sign-off</h2>
      <p>
        The payout of <span className="mono">{money(payout)}</span> is over the
        $1,000.00 limit, so the payment is held until a handler signs off.
      </p>
      <div className="row">
        <label>
          Handler{" "}
          <select
            value={handlerId}
            onChange={(event) => {
              setHandlerId(event.target.value);
            }}
          >
            <option value="">Choose a handler</option>
            {handlers?.map((handler) => (
              <option key={handler.handler_id} value={handler.handler_id}>
                {handler.name}
              </option>
            ))}
          </select>
        </label>
        <button type="button" disabled={!handlerId} onClick={signOff}>
          Sign off and pay
        </button>
      </div>
      {error && <p className="error">{error}</p>}
    </section>
  );
}

export function StepsPanel({ steps }: Readonly<{ steps: Step[] }>) {
  return (
    <section className="panel">
      <h2>What the agent did</h2>
      {steps.length === 0 ? (
        <p className="muted">No steps yet.</p>
      ) : (
        <ol className="steps">
          {steps.map((step) => (
            <li key={step.step_id} className={`step step-${step.kind}`}>
              <span className="step-kind">{STEP_LABELS[step.kind]}</span>
              {step.content.length > 240 ? (
                <details>
                  <summary className="mono">
                    {step.content.slice(0, 160)}
                  </summary>
                  <pre className="mono">{step.content}</pre>
                </details>
              ) : (
                <span className={step.kind === "reply" ? undefined : "mono"}>
                  {step.content}
                </span>
              )}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

export function PolicyPanel({ policyId }: Readonly<{ policyId: string }>) {
  const { data: policy } = useResource<Policy>(`/api/policies/${policyId}`);
  if (!policy) return null;
  return (
    <section className="panel">
      <h2>Policy {policy.policy_id}</h2>
      <dl className="facts">
        <dt>Plan</dt>
        <dd>{policy.plan_details.name}</dd>
        <dt>Bought</dt>
        <dd className="mono">{policy.purchased_on}</dd>
        <dt>Trip</dt>
        <dd>
          {policy.trip.destination},{" "}
          <span className="mono">
            {policy.trip.departs_on} to {policy.trip.returns_on}
          </span>
        </dd>
        <dt>Trip cost</dt>
        <dd className="mono">{money(policy.trip.trip_cost)}</dd>
        <dt>Travelers</dt>
        <dd>{policy.travelers.join(", ")}</dd>
        <dt>Deductible</dt>
        <dd className="mono">{money(policy.plan_details.deductible)}</dd>
        <dt>Add-ons</dt>
        <dd>{policy.add_on_details.map((a) => a.name).join(", ") || "None"}</dd>
      </dl>
    </section>
  );
}

export function CustomerPanel({
  customerId,
}: Readonly<{ customerId: string }>) {
  const { data: customer } = useResource<Customer>(
    `/api/customers/${customerId}`,
  );
  if (!customer) return null;
  return (
    <section className="panel">
      <h2>{customer.name}</h2>
      <p className="muted">
        Customer since <span className="mono">{customer.customer_since}</span>
      </p>
      <h3>Earlier claims</h3>
      {customer.previous_claims.length === 0 ? (
        <p className="muted">None.</p>
      ) : (
        <ul className="plain">
          {customer.previous_claims.map((previous) => (
            <li key={previous.claim_id}>
              <span className="mono">{previous.filed_on}</span>{" "}
              {previous.summary} ({previous.outcome},{" "}
              <span className="mono">{money(previous.amount_paid)}</span>)
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

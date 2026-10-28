import { useState } from "react";
import { postJson, type Claim, type Step } from "./api";
import {
  Attempts,
  CustomerPanel,
  DecisionPanel,
  PolicyPanel,
  ReadPanel,
  SignOffPanel,
  StepsPanel,
} from "./ClaimParts";
import { label, money } from "./format";
import { StatusBadge } from "./StatusBadge";
import { useResource } from "./useResource";

function stillRunning(claim: Claim | undefined, steps: Step[] | undefined) {
  if (claim?.status === "in_progress") return true;
  const last = steps?.at(-1);
  return last !== undefined && last.kind !== "reply" && last.kind !== "error";
}

export function ClaimPage({ claimId }: Readonly<{ claimId: string }>) {
  const [started, setStarted] = useState(false);
  const [runError, setRunError] = useState<string>();
  const [live, setLive] = useState(false);
  const claimPath = `/api/claims/${claimId}`;
  const claimResource = useResource<Claim>(claimPath, live ? 1000 : null);
  const stepsResource = useResource<Step[]>(
    `${claimPath}/steps`,
    live ? 1000 : null,
  );
  const claim = claimResource.data;
  const steps = stepsResource.data ?? [];
  const nowLive =
    (started && claim?.status === "waiting") ||
    stillRunning(claim, stepsResource.data);
  if (nowLive !== live) setLive(nowLive);

  if (claimResource.error)
    return (
      <p className="error">Could not load the claim: {claimResource.error}</p>
    );
  if (!claim) return <p className="muted">Loading the claim.</p>;

  const reload = () => {
    setStarted(false);
    claimResource.reload();
    stepsResource.reload();
  };

  const runAgent = () => {
    setStarted(true);
    setRunError(undefined);
    postJson(`${claimPath}/run`).then(reload, (reason: unknown) => {
      setRunError(String(reason));
      setStarted(false);
    });
  };

  return (
    <>
      <p>
        <a href="#/">Back to the queue</a>
      </p>
      <header className="claim-head">
        <h1 className="mono">{claim.claim_id}</h1>
        <StatusBadge status={claim.status} />
        <Attempts count={claim.attempts} />
        {claim.status === "waiting" && !started && (
          <button type="button" onClick={runAgent}>
            Run the agent
          </button>
        )}
      </header>
      <p className="lead">{claim.summary}</p>
      {runError && <p className="error">{runError}</p>}
      <div className="columns">
        <div>
          {claim.status === "waiting_for_signoff" && (
            <SignOffPanel claim={claim} onDone={reload} />
          )}
          <DecisionPanel claim={claim} />
          <ReadPanel steps={steps} />
          <StepsPanel steps={steps} />
        </div>
        <div>
          <section className="panel">
            <h2>The claim</h2>
            <dl className="facts">
              <dt>Type</dt>
              <dd>{label(claim.claim_type)}</dd>
              <dt>Incident</dt>
              <dd>
                <span className="mono">{claim.incident_date}</span>,{" "}
                {claim.incident_location}
              </dd>
              <dt>Submitted</dt>
              <dd className="mono">{claim.submitted_on}</dd>
              <dt>Claimed</dt>
              <dd className="mono">{money(claim.amount_claimed)}</dd>
            </dl>
            <h3>The customer's story</h3>
            <p>{claim.story}</p>
            <h3>Items</h3>
            <ul className="plain">
              {claim.items.map((item) => (
                <li key={item.description}>
                  {item.description}{" "}
                  <span className="mono">{money(item.amount)}</span>
                </li>
              ))}
            </ul>
            <h3>Documents</h3>
            {claim.documents.map((doc) => (
              <details key={doc.name} className="document">
                <summary>{doc.name}</summary>
                <p>{doc.content}</p>
              </details>
            ))}
          </section>
          <PolicyPanel policyId={claim.policy_id} />
          <CustomerPanel customerId={claim.customer_id} />
        </div>
      </div>
    </>
  );
}

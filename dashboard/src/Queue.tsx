import type { ClaimSummary } from "./api";
import { label, money, STATUS_COLORS, STATUS_LABELS, STATUSES } from "./format";
import { RunPanel } from "./RunPanel";
import { StatusBadge } from "./StatusBadge";
import { useResource } from "./useResource";

export function Queue() {
  const { data: claims, error } = useResource<ClaimSummary[]>(
    "/api/claims",
    3000,
  );

  if (error) return <p className="error">Could not load the queue: {error}</p>;
  if (!claims) return <p className="muted">Loading the queue.</p>;

  return (
    <>
      <section className="tiles" aria-label="Claims by state">
        {STATUSES.map((status) => (
          <div className="tile" key={status}>
            <div className="count">
              {claims.filter((claim) => claim.status === status).length}
            </div>
            <div className="label">
              <span
                className="dot"
                style={{ background: STATUS_COLORS[status] }}
              />
              {STATUS_LABELS[status]}
            </div>
          </div>
        ))}
      </section>
      <RunPanel
        waiting={claims.filter((claim) => claim.status === "waiting").length}
      />
      <section className="panel">
        <h2>Claims queue</h2>
        <div className="scroll">
          <table>
            <thead>
              <tr>
                <th>Claim</th>
                <th>Customer</th>
                <th>Type</th>
                <th>Summary</th>
                <th className="number">Claimed</th>
                <th>State</th>
                <th className="number">Payout</th>
              </tr>
            </thead>
            <tbody>
              {claims.map((claim) => (
                <tr key={claim.claim_id}>
                  <td className="mono">
                    <a href={`#/claims/${claim.claim_id}`}>{claim.claim_id}</a>
                  </td>
                  <td>{claim.customer_name}</td>
                  <td>{label(claim.claim_type)}</td>
                  <td>{claim.summary}</td>
                  <td className="number">{money(claim.amount_claimed)}</td>
                  <td>
                    <StatusBadge status={claim.status} />
                    {claim.decision && (
                      <div className="muted">{label(claim.decision)}</div>
                    )}
                  </td>
                  <td className="number">
                    {claim.payout === null ? "" : money(claim.payout)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

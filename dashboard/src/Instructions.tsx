import type { Instructions as AgentInstructions } from "./api";
import { useResource } from "./useResource";

export function Instructions() {
  const { data, error } = useResource<AgentInstructions>("/api/instructions");

  if (error)
    return <p className="error">Could not load the instructions: {error}</p>;
  if (!data) return <p className="muted">Loading the instructions.</p>;

  return (
    <>
      <section className="panel">
        <h2>Running the queue</h2>
        <p className="muted">
          What the UnderCover Agent reads before each run of the queue. Read
          only.
        </p>
        <pre className="prose">{data.queue}</pre>
      </section>
      <section className="panel">
        <h2>Working a claim</h2>
        <p className="muted">
          What each claim agent reads before it works a claim. Read only.
        </p>
        <pre className="prose">{data.claim}</pre>
      </section>
    </>
  );
}

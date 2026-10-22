import { useResource } from "./useResource";

export function Instructions() {
  const { data, error } = useResource<{ instructions: string }>(
    "/api/instructions",
  );

  if (error)
    return <p className="error">Could not load the instructions: {error}</p>;
  if (!data) return <p className="muted">Loading the instructions.</p>;

  return (
    <section className="panel">
      <h2>The agent's instructions</h2>
      <p className="muted">
        What the UnderCover Agent reads before each claim. Read only.
      </p>
      <pre className="prose">{data.instructions}</pre>
    </section>
  );
}

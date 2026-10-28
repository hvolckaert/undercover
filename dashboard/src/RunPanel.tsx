import { useState } from "react";
import { postJson, type Run } from "./api";
import { RUN_LABELS, TODO_COLORS, TODO_LABELS } from "./format";
import { useResource } from "./useResource";

function RunDetails({ run }: Readonly<{ run: Run }>) {
  const finished = run.todos.filter(
    (todo) => todo.status === "done" || todo.status === "for_handler",
  ).length;
  return (
    <>
      <p className="muted">
        {RUN_LABELS[run.status]}, up to {run.max_claims}{" "}
        {run.max_claims === 1 ? "claim" : "claims"}, started{" "}
        <span className="mono">
          {run.started_at.slice(0, 16).replace("T", " ")} UTC
        </span>
      </p>
      {run.problem && <p className="error">{run.problem}</p>}
      <h3>
        To-do list{" "}
        {run.todos.length > 0 && (
          <span className="muted">
            ({finished} of {run.todos.length} finished)
          </span>
        )}
      </h3>
      {run.todos.length === 0 ? (
        <p className="muted">The agent has not written its list yet.</p>
      ) : (
        <ol className="todos">
          {run.todos.map((todo) => (
            <li key={todo.task} className={`todo todo-${todo.status}`}>
              <span
                className="dot"
                style={{ background: TODO_COLORS[todo.status] }}
              />
              <span>{todo.task}</span>
              <span className="muted">{TODO_LABELS[todo.status]}</span>
            </li>
          ))}
        </ol>
      )}
      {run.summary && (
        <>
          <h3>Summary</h3>
          <p className="prose">{run.summary}</p>
        </>
      )}
    </>
  );
}

export function RunPanel({ waiting }: Readonly<{ waiting: number }>) {
  const [maxClaims, setMaxClaims] = useState(5);
  const [error, setError] = useState<string>();
  const [polling, setPolling] = useState(false);
  const { data: run, reload } = useResource<Run | null>(
    "/api/runs/latest",
    polling ? 2000 : 5000,
  );
  const running = run?.status === "running";
  if (running !== polling) setPolling(running);

  const start = () => {
    setError(undefined);
    postJson("/api/runs", { max_claims: maxClaims }).then(
      reload,
      (reason: unknown) => {
        setError(String(reason));
      },
    );
  };

  return (
    <section className="panel" aria-label="Agent run">
      <h2>Agent run</h2>
      <div className="row">
        <label>
          Claims to work{" "}
          <input
            type="number"
            min={1}
            value={maxClaims}
            onChange={(event) => {
              setMaxClaims(Number(event.target.value));
            }}
          />
        </label>
        <button
          type="button"
          className="secondary"
          disabled={waiting === 0}
          onClick={() => {
            setMaxClaims(waiting);
          }}
        >
          Whole queue
        </button>
        <button
          type="button"
          disabled={running || maxClaims < 1}
          onClick={start}
        >
          Start run
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {run ? (
        <RunDetails run={run} />
      ) : (
        <p className="muted">The agent has not run on the queue yet.</p>
      )}
    </section>
  );
}

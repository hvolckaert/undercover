import type { Run, Section, Status, TodoStatus } from "./api";

const dollars = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
});

export function money(amount: number): string {
  return dollars.format(amount);
}

export function label(code: string): string {
  const words = code.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export const STATUSES: Status[] = [
  "waiting",
  "in_progress",
  "waiting_for_signoff",
  "decided",
  "needs_handler",
];

export const STATUS_LABELS: Record<Status, string> = {
  waiting: "Waiting",
  in_progress: "In progress",
  waiting_for_signoff: "Waiting for sign-off",
  decided: "Decided",
  needs_handler: "Left for a handler",
};

export const STATUS_COLORS: Record<Status, string> = {
  waiting: "var(--cerulean)",
  in_progress: "var(--marigold)",
  waiting_for_signoff: "var(--coral)",
  decided: "var(--sea-green)",
  needs_handler: "var(--raspberry)",
};

export const TODO_LABELS: Record<TodoStatus, string> = {
  to_do: "To do",
  in_progress: "In progress",
  done: "Done",
  for_handler: "Left for a handler",
};

export const TODO_COLORS: Record<TodoStatus, string> = {
  to_do: "var(--cerulean)",
  in_progress: "var(--marigold)",
  done: "var(--sea-green)",
  for_handler: "var(--raspberry)",
};

export const RUN_LABELS: Record<Run["status"], string> = {
  running: "Running",
  finished: "Finished",
  stopped: "Stopped",
};

export const DOCUMENT_LABELS: Record<Section["document"], string> = {
  policy_wording: "Policy wording",
  claims_manual: "Claims manual",
};

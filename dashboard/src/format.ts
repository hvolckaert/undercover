import type { Status } from "./api";

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
];

export const STATUS_LABELS: Record<Status, string> = {
  waiting: "Waiting",
  in_progress: "In progress",
  waiting_for_signoff: "Waiting for sign-off",
  decided: "Decided",
};

export const STATUS_COLORS: Record<Status, string> = {
  waiting: "var(--cerulean)",
  in_progress: "var(--marigold)",
  waiting_for_signoff: "var(--coral)",
  decided: "var(--sea-green)",
};

import type { Section, Step } from "./api";

export function attempts(steps: Step[]): Step[][] {
  const byThread = new Map<string, Step[]>();
  for (const step of steps) {
    byThread.set(step.thread_id, [
      ...(byThread.get(step.thread_id) ?? []),
      step,
    ]);
  }
  return [...byThread.values()];
}

const READ_RESULT = "read_section: ";

export function sectionsRead(steps: Step[]): Section[] {
  const read = new Map<string, Section>();
  for (const step of steps) {
    if (
      step.kind === "tool_result" &&
      step.content.startsWith(READ_RESULT + "{")
    ) {
      const section = JSON.parse(
        step.content.slice(READ_RESULT.length),
      ) as Section;
      read.set(`${section.document} ${section.section}`, section);
    }
  }
  return [...read.values()];
}

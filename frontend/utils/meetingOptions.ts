import type { ParameterRange } from "../types/meeting";

export const FAIRNESS_STEP = 0.1;

export function parseTravelLimit(input: string, { min, max }: ParameterRange): number | null {
  const seconds = Number(input);
  return input.trim() && Number.isInteger(seconds) && seconds >= min && seconds <= max ? seconds : null;
}

export function fairnessAtStep(step: number, { min, max }: ParameterRange): number {
  return Math.min(max, Math.max(min, Number((min + step * FAIRNESS_STEP).toFixed(12))));
}

export function parseSpacing(input: string, { min, max }: ParameterRange): number | null {
  const meters = Number(input);
  return input.trim() && Number.isFinite(meters) && meters >= min && meters <= max ? meters : null;
}

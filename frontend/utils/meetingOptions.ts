import type { ParameterRange } from "../types/meeting";

export function parseTravelLimit(input: string, { min, max }: ParameterRange): number | null {
  const seconds = Number(input);
  return input.trim() && Number.isInteger(seconds) && seconds >= min && seconds <= max ? seconds : null;
}

export function parseSpacing(input: string, { min, max }: ParameterRange): number | null {
  const meters = Number(input);
  return input.trim() && Number.isFinite(meters) && meters >= min && meters <= max ? meters : null;
}

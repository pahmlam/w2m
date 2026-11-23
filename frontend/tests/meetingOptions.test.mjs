import assert from "node:assert/strict";
import { test } from "node:test";
import { fairnessAtStep, parseSpacing, parseTravelLimit } from "../utils/meetingOptions.ts";

test("spacing accepts fractional meters and validates the configured boundaries", () => {
  const range = { min: 0, max: 5000 };
  for (const value of ["0", "500.5", "5000"]) assert.equal(parseSpacing(value, range), Number(value));
  for (const value of ["", "-1", "5000.1", "Infinity"]) assert.equal(parseSpacing(value, range), null);
});

test("accepts exact integer seconds at both API bounds and rejects invalid input", () => {
  const range = { min: 300, max: 7200 };
  for (const seconds of [300, 3661, 7200]) {
    assert.equal(parseTravelLimit(String(seconds), range), seconds);
  }
  for (const input of ["", " ", "NaN", "301.5", "299", "7201"]) {
    assert.equal(parseTravelLimit(input, range), null);
  }
});

test("uses decimal fairness steps and clamps to the advertised limits", () => {
  assert.equal(fairnessAtStep(3, { min: 0, max: 1 }), 0.3);
  assert.equal(fairnessAtStep(2, { min: 0.3, max: 1 }), 0.5);
  assert.equal(fairnessAtStep(99, { min: 0, max: 0.8 }), 0.8);
});

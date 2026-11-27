import type { MeetingMapConfig } from "@/services/meetingApi";
import type { ObjectiveType } from "@/types/meeting";
import { parseSpacing, parseTravelLimit } from "@/utils/meetingOptions";

interface OptionValues { time: string; count: number; spacing: string }

export default function MeetingOptions({ limits, values, onChange, objectiveType, onToggleObjective }: {
  limits: MeetingMapConfig["limits"];
  values: OptionValues;
  onChange: (values: OptionValues) => void;
  objectiveType: ObjectiveType;
  onToggleObjective: () => void;
}) {
  const { time: timeInput, count, spacing } = values;
  const onTimeChange = (value: string) => onChange({ ...values, time: value });
  const validTime = parseTravelLimit(timeInput, limits.max_travel_seconds) !== null;
  const validSpacing = parseSpacing(spacing, limits.min_spacing_meters) !== null;
  const time = limits.max_travel_seconds;
  return (
    <div className="meeting-options">
      <div className="fairness-control">
        <button className="fairness-mode" type="button" title="Switch fairness mode" onClick={onToggleObjective}>
          {objectiveType === "owa_geometric" ? "Mode · Fastest for the group" : "Mode · Similar travel times"}
        </button>
      </div>
      <div className="travel-controls">
        <strong>Max travel per person</strong>
        <div className="time-presets" role="group" aria-label="Maximum travel time presets">
          {[10, 20, 30, 60, 120].filter((min) => min * 60 >= time.min && min * 60 <= time.max)
            .map((min) => <button key={min} type="button" aria-pressed={validTime && Number(timeInput) === min * 60}
              onClick={() => onTimeChange(String(min * 60))}>{min} min</button>)}
        </div>
        <details className="custom-time">
          <summary>Custom limit</summary>
          <label htmlFor="meeting-time">Max travel (seconds)</label>
          <input id="meeting-time" type="number" min={time.min} max={time.max} step={1} value={timeInput}
            aria-invalid={!validTime} aria-describedby="meeting-time-hint"
            onChange={(event) => onTimeChange(event.currentTarget.value)} />
          <small id="meeting-time-hint" className={validTime ? undefined : "origin-error"}>
            {validTime ? `${time.min}–${time.max} seconds` : `Enter whole seconds from ${time.min} to ${time.max}.`}
          </small>
        </details>
        <div className="advanced-options">
          <label>Results <select value={count} onChange={(event) => onChange({ ...values, count: Number(event.target.value) })}>
            {Array.from({ length: limits.top_k.max - limits.top_k.min + 1 }, (_, i) => i + limits.top_k.min)
              .map((value) => <option key={value}>{value}</option>)}
          </select></label>
          <label>Minimum spacing (m) <input type="number" min={limits.min_spacing_meters.min}
            max={limits.min_spacing_meters.max} step="any" value={spacing} aria-invalid={!validSpacing}
            aria-describedby={!validSpacing ? "spacing-error" : undefined}
            onChange={(event) => onChange({ ...values, spacing: event.currentTarget.value })} /></label>
        </div>
        {!validSpacing && <small id="spacing-error" className="origin-error">
          Enter a spacing from {limits.min_spacing_meters.min} to {limits.min_spacing_meters.max} m.
        </small>}
      </div>
    </div>
  );
}

import type { MeetingMapConfig } from "@/services/meetingApi";
import type { ObjectiveType } from "@/types/meeting";
import { FAIRNESS_STEP, fairnessAtStep, parseSpacing, parseTravelLimit } from "@/utils/meetingOptions";

const fairnessNumber = new Intl.NumberFormat("en", { minimumFractionDigits: 1, maximumFractionDigits: 20 });

interface OptionValues { phi: number; time: string; count: number; spacing: string }

export default function MeetingOptions({ limits, values, onChange, objectiveType, onToggleObjective }: {
  limits: MeetingMapConfig["limits"];
  values: OptionValues;
  onChange: (values: OptionValues) => void;
  objectiveType: ObjectiveType;
  onToggleObjective: () => void;
}) {
  const { phi, time: timeInput, count, spacing } = values;
  const onPhiChange = (value: number) => onChange({ ...values, phi: value });
  const onTimeChange = (value: string) => onChange({ ...values, time: value });
  const validTime = parseTravelLimit(timeInput, limits.max_travel_seconds) !== null;
  const validSpacing = parseSpacing(spacing, limits.min_spacing_meters) !== null;
  const steps = (phi - limits.phi.min) / FAIRNESS_STEP;
  const offStep = Math.abs(steps - Math.round(steps)) > 1e-9;
  const time = limits.max_travel_seconds;
  return (
    <div className="meeting-options">
      <div className="fairness-control">
        <label htmlFor="meeting-fairness">Fairness</label>
        <output htmlFor="meeting-fairness">{fairnessNumber.format(phi)}</output>
        <input id="meeting-fairness" type="range" min={limits.phi.min} max={limits.phi.max}
          step={offStep ? "any" : FAIRNESS_STEP} value={phi} aria-valuetext={fairnessNumber.format(phi)}
          aria-describedby="fairness-endpoints"
          onChange={(event) => {
            const next = event.currentTarget.valueAsNumber;
            const tick = Math.round((next - limits.phi.min) / FAIRNESS_STEP);
            onPhiChange(next === limits.phi.max ? next : fairnessAtStep(tick, limits.phi));
          }}
          onKeyDown={(event) => {
            // A backend default may be between slider steps. Move to the adjacent step on the first arrow press.
            if (!offStep) return;
            if (event.key === "ArrowRight" || event.key === "ArrowUp") {
              event.preventDefault();
              onPhiChange(fairnessAtStep(Math.floor(steps) + 1, limits.phi));
            } else if (event.key === "ArrowLeft" || event.key === "ArrowDown") {
              event.preventDefault();
              onPhiChange(fairnessAtStep(Math.ceil(steps) - 1, limits.phi));
            }
          }} />
        <div className="fairness-endpoints" id="fairness-endpoints"><span>Shortest average time</span><span>More fairness</span></div>
        <button className="fairness-mode" type="button" title="Switch fairness mode" onClick={onToggleObjective}>
          {objectiveType === "owa_geometric" ? "Mode · Prioritize longest trip" : "Mode · Similar travel times"}
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

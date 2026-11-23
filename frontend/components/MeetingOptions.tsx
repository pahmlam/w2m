import type { MeetingMapConfig } from "@/services/meetingApi";
import { FAIRNESS_STEP, fairnessAtStep } from "@/utils/meetingOptions";

const fairnessNumber = new Intl.NumberFormat("vi", { minimumFractionDigits: 1, maximumFractionDigits: 20 });

export default function MeetingOptions({ limits, phi, timeInput, validTime, onPhiChange, onTimeChange }: {
  limits: MeetingMapConfig["limits"];
  phi: number;
  timeInput: string;
  validTime: boolean;
  onPhiChange: (value: number) => void;
  onTimeChange: (value: string) => void;
}) {
  const steps = (phi - limits.phi.min) / FAIRNESS_STEP;
  const offStep = Math.abs(steps - Math.round(steps)) > 1e-9;
  const time = limits.max_travel_seconds;
  return (
    <fieldset className="meeting-options">
      <legend>Tùy chọn tìm điểm gặp</legend>
      <label htmlFor="meeting-fairness">Mức ưu tiên công bằng</label>
      <output htmlFor="meeting-fairness">{fairnessNumber.format(phi)}</output>
      <input id="meeting-fairness" type="range" min={limits.phi.min} max={limits.phi.max}
        step={offStep ? "any" : FAIRNESS_STEP} value={phi} aria-valuetext={fairnessNumber.format(phi)}
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
      <div className="fairness-endpoints"><span>Nhanh cho cả nhóm</span><span>Công bằng nhất</span></div>
      <label htmlFor="meeting-time">Giới hạn thời gian mỗi người (giây)</label>
      <input id="meeting-time" type="number" min={time.min} max={time.max} step={1} value={timeInput}
        aria-invalid={!validTime} aria-describedby="meeting-time-hint"
        onChange={(event) => onTimeChange(event.currentTarget.value)} />
      <small id="meeting-time-hint" className={validTime ? undefined : "origin-error"}>
        {validTime ? `${time.min}–${time.max} giây` : `Nhập số giây nguyên từ ${time.min} đến ${time.max}.`}
      </small>
    </fieldset>
  );
}

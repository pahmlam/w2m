import type { MeetingOutcome } from "@/services/meetingApi";
import { formatMinutes, ORIGIN_COLORS } from "@/utils/meetingDisplay";
import { ORIGIN_IDS, type OriginId } from "@/utils/originLocation";

export default function MeetingResults({ outcome, stale, selectedRank, onSelect, hiddenRoutes, onToggleRoute }: {
  outcome: MeetingOutcome;
  stale: boolean;
  selectedRank: number | null;
  onSelect: (rank: number) => void;
  hiddenRoutes: ReadonlySet<OriginId>;
  onToggleRoute: (id: OriginId) => void;
}) {
  return (
    <section className="meeting-results" aria-labelledby="meeting-results-heading">
      <h2 id="meeting-results-heading">Kết quả điểm gặp</h2>
      <p role="status">
        {stale ? "Chưa cập nhật."
          : outcome.status === "success" ? `Tìm thấy ${outcome.results.length} điểm gặp.`
          : "Không có điểm gặp trong giới hạn thời gian."}
      </p>
      <div className={stale ? "meeting-results-stale" : undefined}>
        {outcome.status === "success" ? (
          <>
            <p>Thời gian ước lượng theo phút, đã gồm thời gian tiếp cận.</p>
            {selectedRank !== null && (
              <fieldset className="route-options">
                <legend>Tuyến đến điểm {selectedRank}</legend>
                {ORIGIN_IDS.map((id) => (
                  <label key={id}>
                    <input type="checkbox" checked={!hiddenRoutes.has(id)} onChange={() => onToggleRoute(id)} />
                    <span className="route-key" style={{ backgroundColor: ORIGIN_COLORS[id] }} aria-hidden="true" />
                    Tuyến {id}
                  </label>
                ))}
              </fieldset>
            )}
            <ol>
              {outcome.results.map((result) => (
                <li key={result.rank} value={result.rank}>
                  {!stale && (
                    <div className="meeting-result-actions">
                      <button type="button" aria-pressed={result.rank === selectedRank}
                        onClick={() => onSelect(result.rank)}>
                        Xem tuyến đến điểm {result.rank}
                      </button>
                      {result.rank === selectedRank && <a href="#meeting-map">Xem bản đồ</a>}
                    </div>
                  )}
                  <strong>Điểm nhóm {formatMinutes(result.score)} phút</strong>
                  <span>Vĩ độ {result.location.lat.toFixed(5)} · Kinh độ {result.location.lon.toFixed(5)}</span>
                  <dl className="person-times" aria-label="Thời gian A–D">
                    {outcome.snaps.map(({ id }) => (
                      <div key={id}><dt>{id}</dt><dd>{formatMinutes(result.travel_times[id])}</dd></div>
                    ))}
                  </dl>
                  <dl className="summary-times" aria-label="Thống kê thời gian">
                    <div><dt>Xa nhất</dt><dd>{formatMinutes(result.max_time)}</dd></div>
                    <div><dt>Nhỏ nhất</dt><dd>{formatMinutes(result.min_time)}</dd></div>
                    <div><dt>Chênh lệch</dt><dd>{formatMinutes(result.difference)}</dd></div>
                    <div><dt>Trung bình</dt><dd>{formatMinutes(result.avg_time)}</dd></div>
                  </dl>
                </li>
              ))}
            </ol>
          </>
        ) : (
          <p>
            {outcome.minimum && (
              <>Cần {outcome.minimum.lowerBound ? "hơn " : "ít nhất "}
                {formatMinutes(outcome.minimum.seconds)} phút mỗi người.{" "}</>
            )}
            Hãy thử tăng giới hạn thời gian hoặc điều chỉnh vị trí xuất phát.
          </p>
        )}
      </div>
    </section>
  );
}

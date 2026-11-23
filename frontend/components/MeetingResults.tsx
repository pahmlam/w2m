import type { MeetingOutcome } from "@/services/meetingApi";

const minutes = new Intl.NumberFormat("vi", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

export default function MeetingResults({ outcome, stale }: { outcome: MeetingOutcome; stale: boolean }) {
  return (
    <section className="meeting-results" aria-labelledby="meeting-results-heading">
      <h2 id="meeting-results-heading">Kết quả điểm gặp</h2>
      <p role="status">
        {stale ? "Chưa cập nhật. Hãy tìm lại với các vị trí mới."
          : outcome.status === "success" ? `Tìm thấy ${outcome.results.length} điểm gặp.`
          : "Không có điểm gặp trong giới hạn thời gian."}
      </p>
      <div className={stale ? "meeting-results-stale" : undefined}>
        {outcome.status === "success" ? (
          <>
            <p>Điểm nhóm theo thời gian ước lượng</p>
            <ol>
              {outcome.results.map(({ rank, location, score }) => (
                <li key={rank} value={rank}>
                  <strong>{minutes.format(score / 60)} phút</strong>
                  <span>Vĩ độ {location.lat.toFixed(5)} · Kinh độ {location.lon.toFixed(5)}</span>
                </li>
              ))}
            </ol>
          </>
        ) : (
          <p>
            {outcome.minimum && (
              <>Cần {outcome.minimum.lowerBound ? "hơn " : "ít nhất "}
                {minutes.format(outcome.minimum.seconds / 60)} phút mỗi người.{" "}</>
            )}
            Hãy thử điều chỉnh vị trí xuất phát.
          </p>
        )}
      </div>
    </section>
  );
}

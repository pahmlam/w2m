import type { OriginSnap } from "@/services/meetingApi";
import { formatMinutes } from "@/utils/meetingDisplay";

const meters = new Intl.NumberFormat("vi", { maximumFractionDigits: 1 });

export default function SnapDetails({ snaps }: { snaps: OriginSnap[] }) {
  return (
    <section className="snap-details" aria-labelledby="snap-details-heading">
      <h2 id="snap-details-heading">Tiếp cận đường</h2>
      <dl>
        {snaps.map(({ id, snap_distance_m, access_seconds, snapped }) => (
          <div key={id}>
            <dt>{id}</dt>
            <dd>
              <span>{meters.format(snap_distance_m)} m · {formatMinutes(access_seconds)} phút</span>
              <span>Điểm snap {snapped.lat.toFixed(5)}, {snapped.lon.toFixed(5)}</span>
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

import type { OriginSnap } from "@/services/meetingApi";
import { formatMinutes } from "@/utils/meetingDisplay";

const meters = new Intl.NumberFormat("en", { maximumFractionDigits: 1 });

export default function SnapDetails({ snaps }: { snaps: OriginSnap[] }) {
  return (
    <details className="snap-details">
      <summary>Road access details</summary>
      <dl>
        {snaps.map(({ id, snap_distance_m, access_seconds, snapped }) => (
          <div key={id}>
            <dt>{id}</dt>
            <dd>
              <span>{meters.format(snap_distance_m)} m · {formatMinutes(access_seconds)} min</span>
              <span>Road access point {snapped.lat.toFixed(5)}, {snapped.lon.toFixed(5)}</span>
            </dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

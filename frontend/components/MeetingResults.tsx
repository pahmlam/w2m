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
  if (outcome.status === "empty") return <p className="empty-results">
    {outcome.minimum && (
      <>Allow {outcome.minimum.lowerBound ? "more than" : "at least"} {formatMinutes(outcome.minimum.seconds)} min per person.{" "}</>
    )}
    Try raising the travel limit or moving a pin.
  </p>;

  const scale = Math.max(0, ...outcome.results.flatMap((result) => Object.values(result.travel_times)));
  return (
    <div className={stale ? "meeting-results meeting-results-stale" : "meeting-results"}>
      <ol aria-label="Ranked spots">
        {outcome.results.map((result) => (
          <li key={result.node_id} value={result.rank} className={result.rank === selectedRank ? "spot-selected" : undefined}>
            <div className="spot-heading">
              <span className="rank-badge" aria-hidden="true">{result.rank}</span>
              <div className="spot-label">
                {stale ? <strong>Spot #{result.rank}</strong> : (
                  <button type="button" aria-pressed={result.rank === selectedRank} onClick={() => onSelect(result.rank)}>
                    Spot #{result.rank}
                  </button>
                )}
                <small>Latitude {result.location.lat.toFixed(5)} · Longitude {result.location.lon.toFixed(5)}</small>
              </div>
              <div className="spot-score"><strong>{formatMinutes(result.score)} <small>min</small></strong><small>Group score</small></div>
            </div>
            <dl className="person-times" aria-label="Travel times A–D">
              {ORIGIN_IDS.map((id) => {
                const total = result.travel_times[id];
                const access = outcome.snaps.find((snap) => snap.id === id)?.access_seconds ?? 0;
                return <div className="time-row" key={id}>
                  <dt style={{ backgroundColor: ORIGIN_COLORS[id] }}>{id}</dt>
                  <dd className="time-track" aria-hidden="true">
                    <span className="time-bar" style={{ width: `${scale ? 100 * total / scale : 0}%`, backgroundColor: ORIGIN_COLORS[id] }}>
                      <span className="access-bar" style={{ width: `${total ? Math.min(100, 100 * access / total) : 0}%` }} />
                    </span>
                  </dd>
                  <dd>{formatMinutes(total)} min</dd>
                </div>;
              })}
            </dl>
            <dl className="summary-times" aria-label="Travel time summary">
              <div><dt>Longest</dt><dd>{formatMinutes(result.max_time)} min</dd></div>
              <div><dt>Shortest</dt><dd>{formatMinutes(result.min_time)} min</dd></div>
              <div><dt>Gap</dt><dd>{formatMinutes(result.difference)} min</dd></div>
              <div><dt>Average</dt><dd>{formatMinutes(result.avg_time)} min</dd></div>
            </dl>
            {selectedRank === result.rank && (
              <fieldset className="route-options">
                <legend>Routes to spot {selectedRank}</legend>
                {ORIGIN_IDS.map((id) => (
                  <label key={id}>
                    <input type="checkbox" checked={!hiddenRoutes.has(id)} onChange={() => onToggleRoute(id)} />
                    <span className="route-key" style={{ backgroundColor: ORIGIN_COLORS[id] }} aria-hidden="true" />
                    Route {id}
                  </label>
                ))}
                <a href="#meeting-map">View map</a>
              </fieldset>
            )}
          </li>
        ))}
      </ol>
      <p className="map-disclaimer">
        Estimated times include road access, shown as stripes. Turn restrictions are not modeled.
        Meeting spots may be unsuitable for stopping or parking.
      </p>
    </div>
  );
}

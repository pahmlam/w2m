import { useEffect } from "react";
import type { Map } from "maplibre-gl";

import type { OriginSnap } from "@/services/meetingApi";
import { snapFeatures } from "@/utils/meetingDisplay";

const SOURCE = "w2m-snaps";
export const SNAP_ACCESS_LAYER = "w2m-snap-access";
const POINT_LAYER = "w2m-snap-points";

export default function SnapLayer({ map, snaps }: { map: Map; snaps: OriginSnap[] }) {
  useEffect(() => {
    map.addSource(SOURCE, { type: "geojson", data: snapFeatures(snaps) });
    map.addLayer({
      id: SNAP_ACCESS_LAYER, source: SOURCE, type: "line",
      filter: ["==", ["geometry-type"], "LineString"],
      paint: { "line-color": "#8a461c", "line-width": 2.5, "line-dasharray": [2, 2] },
    });
    map.addLayer({
      id: POINT_LAYER, source: SOURCE, type: "circle",
      filter: ["==", ["geometry-type"], "Point"],
      paint: {
        // Keep the snap outline visible beside origin markers at the city-wide zoom.
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 13, 20, 17, 4],
        "circle-opacity": ["interpolate", ["linear"], ["zoom"], 13, 0, 17, 1],
        "circle-color": "#fff",
        "circle-stroke-color": "#8a461c",
        "circle-stroke-width": 2,
      },
    });
    return () => {
      if (!map.getSource(SOURCE)) return;
      map.removeLayer(POINT_LAYER);
      map.removeLayer(SNAP_ACCESS_LAYER);
      map.removeSource(SOURCE);
    };
  }, [map, snaps]);

  return null;
}

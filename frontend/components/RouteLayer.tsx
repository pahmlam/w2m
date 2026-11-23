import { useEffect } from "react";
import type { FilterSpecification, Map } from "maplibre-gl";

import { SNAP_ACCESS_LAYER } from "@/components/SnapLayer";
import type { DisplayedResult } from "@/services/meetingApi";
import { coordinateBounds, routeFeatures } from "@/utils/meetingDisplay";
import { ORIGIN_IDS, type OriginId } from "@/utils/originLocation";

const SOURCE = "w2m-routes";
const OUTLINE_LAYER = "w2m-route-outline";
const ROUTE_LAYER = "w2m-route-lines";

export default function RouteLayer({ map, routes, hidden }: {
  map: Map;
  routes: DisplayedResult["routes"];
  hidden: ReadonlySet<OriginId>;
}) {
  useEffect(() => {
    const data = routeFeatures(routes, ORIGIN_IDS);
    const before = map.getLayer(SNAP_ACCESS_LAYER) ? SNAP_ACCESS_LAYER : undefined;
    map.addSource(SOURCE, { type: "geojson", data });
    map.addLayer({
      id: OUTLINE_LAYER, source: SOURCE, type: "line",
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": "#fff", "line-width": 7 },
    }, before);
    map.addLayer({
      id: ROUTE_LAYER, source: SOURCE, type: "line",
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": ["get", "color"], "line-width": 4 },
    }, before);
    map.fitBounds(coordinateBounds(data.features.flatMap((feature) => feature.geometry.coordinates)),
      { padding: 48, duration: 0, maxZoom: 16 });

    return () => {
      if (!map.getSource(SOURCE)) return;
      map.removeLayer(ROUTE_LAYER);
      map.removeLayer(OUTLINE_LAYER);
      map.removeSource(SOURCE);
    };
  }, [map, routes]);

  useEffect(() => {
    const ids = ORIGIN_IDS.filter((id) => !hidden.has(id));
    const filter: FilterSpecification = ["in", ["get", "id"], ["literal", ids]];
    map.setFilter(OUTLINE_LAYER, filter);
    map.setFilter(ROUTE_LAYER, filter);
  }, [map, routes, hidden]);

  return null;
}

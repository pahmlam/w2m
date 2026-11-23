import { useEffect, useRef } from "react";
import type { Map, Marker } from "maplibre-gl";

import type { DisplayedResult } from "@/services/meetingApi";

export default function MeetingMarkers({ map, MarkerClass, results, selectedRank, onSelect }: {
  map: Map;
  MarkerClass: typeof Marker;
  results: DisplayedResult[];
  selectedRank: number | null;
  onSelect: (rank: number) => void;
}) {
  const markers = useRef<Marker[]>([]);
  useEffect(() => {
    const created = results.map(({ rank, location }) => {
      const element = document.createElement("button");
      element.type = "button";
      element.className = "meeting-marker";
      element.textContent = String(rank);
      element.setAttribute("aria-label", `Spot ${rank} on the map`);
      element.addEventListener("click", (event) => {
        event.stopPropagation();
        onSelect(rank);
      });
      return new MarkerClass({ element, anchor: "bottom", offset: [0, -4] })
        .setLngLat([location.lon, location.lat]).addTo(map);
    });
    markers.current = created;
    return () => created.forEach((marker) => marker.remove());
  }, [map, MarkerClass, results, onSelect]);

  useEffect(() => {
    for (const [index, marker] of markers.current.entries()) {
      marker.getElement().setAttribute("aria-pressed", String(results[index].rank === selectedRank));
    }
  }, [map, MarkerClass, results, onSelect, selectedRank]);

  return null;
}

import { useEffect, useEffectEvent, useRef } from "react";
import type { Map, Marker } from "maplibre-gl";

import type { Location } from "@/types/meeting";
import { ORIGIN_COLORS } from "@/utils/meetingDisplay";
import type { OriginId } from "@/utils/originLocation";

interface Props {
  map: Map;
  MarkerClass: typeof Marker;
  id: OriginId;
  location: Location;
  selected: boolean;
  onMove: (id: OriginId, location: Location) => boolean;
}

export default function OriginMarker({ map, MarkerClass, id, location, selected, onMove }: Props) {
  const markerRef = useRef<Marker>(null);
  const updatePosition = useEffectEvent((marker: Marker) => {
    marker.setLngLat([location.lon, location.lat]);
  });
  const handleDragEnd = useEffectEvent((marker: Marker) => {
    const { lng, lat } = marker.getLngLat().wrap();
    if (!onMove(id, { lat, lon: lng })) updatePosition(marker);
  });

  useEffect(() => {
    const element = document.createElement("div");
    element.className = "origin-marker";
    element.style.backgroundColor = ORIGIN_COLORS[id];
    element.textContent = id;
    element.setAttribute("role", "img");
    element.setAttribute("aria-label", `Friend ${id} location`);
    // Keep the drag's release on the map even when the pointer crosses its controls.
    element.addEventListener("pointerdown", (event) => {
      if (event.button === 0) element.setPointerCapture(event.pointerId);
    });

    const marker = new MarkerClass({ element, draggable: true });
    updatePosition(marker);
    marker.addTo(map);
    marker.on("dragend", () => handleDragEnd(marker));
    markerRef.current = marker;
    return () => {
      marker.remove();
      markerRef.current = null;
    };
  }, [map, MarkerClass, id]);

  useEffect(() => {
    markerRef.current?.setLngLat([location.lon, location.lat]);
  }, [location]);

  useEffect(() => {
    markerRef.current?.getElement().classList.toggle("origin-marker--selected", selected);
  }, [selected]);

  return null;
}

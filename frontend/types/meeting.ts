/** Public contract: docs/spec/W2M-M0-Contract-Addendum.md. */
export interface Location {
  lat: number;
  lon: number;
}

export interface Origin extends Location {
  id: string;
}

export interface Optimization {
  phi: number;
  max_travel_seconds: number;
  top_k: number;
  min_spacing_meters: number;
}

export interface MeetingRequest {
  origins: Origin[];
  travel_mode: "car";
  optimization: Optimization;
}

export interface RerankRequest {
  optimization: Optimization;
}

export type ErrorCode =
  | "INVALID_COORDINATES"
  | "INVALID_PARAMETERS"
  | "OUT_OF_COVERAGE"
  | "SNAP_FAILED"
  | "NO_COMMON_REACHABLE_NODE"
  | "RECOMPUTE_REQUIRED"
  | "GRAPH_UNAVAILABLE"
  | "INTERNAL_ERROR";

export interface ApiError {
  error_code: ErrorCode;
  message: string;
  request_id: string;
}

export interface SnappedOrigin {
  id: string;
  snap_distance_m: number;
  access_seconds: number;
  snapped: Location;
}

export interface Route {
  network_seconds: number;
  access_seconds: number;
  duration_seconds: number;
  distance_meters: number;
  geometry: {
    type: "LineString";
    coordinates: [number, number][];
  };
}

export interface MeetingResult {
  rank: number;
  node_id: number;
  location: Location;
  travel_times: Record<string, number>;
  max_time: number;
  min_time: number;
  difference: number;
  avg_time: number;
  score: number;
  routes: Record<string, Route>;
}

export interface MeetingResponse {
  request_id: string;
  graph_version: string;
  weight_profile_version: string;
  status: "success" | "empty";
  unit: "seconds";
  objective: { type: "owa_geometric"; phi: number; weights: number[] };
  origins: SnappedOrigin[];
  results: MeetingResult[];
  timings_ms: {
    snap: number;
    dijkstra: number;
    scan: number;
    rank: number;
    routes: number;
    total: number;
  };
  error_code?: "NO_COMMON_REACHABLE_NODE" | null;
  message?: string | null;
  min_required_seconds?: number | string | null;
}

export interface Polygon {
  type: "Polygon";
  coordinates: [number, number][][];
}

export interface ParameterRange {
  min: number;
  max: number;
}

export interface MapConfig {
  aoi: Polygon;
  travel_modes: ["car"];
  limits: {
    phi: ParameterRange;
    max_travel_seconds: ParameterRange;
    top_k: ParameterRange;
    min_spacing_meters: ParameterRange;
  };
  defaults: Optimization & { v_access: number };
  graph_version: string;
  weight_profile_version: string;
  source_date: string;
}

export type ChallengeSummary = {
  id: string;
  title: string;
  tagline: string;
  theme_tags: string[];
  start_stop: string;
  start_time: string;
  total_ride_minutes: number;
  total_distance_km: number;
  transfers: number;
  wards: string[];
  badges: string[];
};

export type RestStop = {
  at: string;
  minutes: number;
  suggestion: string;
};

export type Coordinate = {
  lat: number;
  lon: number;
};

export type Geometry = {
  type: 'LineString';
  coordinates: [number, number][];
};

export type Leg = {
  sequence: number;
  line_label: string;
  line_name: string;
  from_stop: string;
  to_stop: string;
  departure: string;
  arrival: string;
  ride_minutes: number;
  distance_km: number;
  notes: string[];
  geometry: Geometry;
  path?: Coordinate[];
  from_coord?: Coordinate;
  to_coord?: Coordinate;
};

export type ChallengeDetail = ChallengeSummary & {
  legs: Leg[];
  rest_stops: RestStop[];
};

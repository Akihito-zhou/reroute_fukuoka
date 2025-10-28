import { useEffect, useMemo } from 'react';
import {
  CircleMarker,
  MapContainer,
  Polyline,
  TileLayer,
  useMap
} from 'react-leaflet';
import type { LatLngBoundsExpression } from 'leaflet';
import { Leg } from '../types/challenge';

type RouteMapProps = {
  legs: Leg[];
};

const colors = ['#22d3ee', '#a855f7', '#f97316', '#ec4899', '#38bdf8', '#facc15'];

const FitBounds: React.FC<{ bounds: LatLngBoundsExpression | null }> = ({ bounds }) => {
  const map = useMap();
  useEffect(() => {
    if (bounds) {
      map.fitBounds(bounds, { padding: [28, 28], maxZoom: 15 });
    }
  }, [bounds, map]);
  return null;
};

const hasFiniteLatLon = (lat?: number, lon?: number): boolean =>
  typeof lat === 'number' && Number.isFinite(lat) && typeof lon === 'number' && Number.isFinite(lon);

const normaliseLegPath = (leg: Leg): [number, number][] => {
  const fromPath =
    leg.path?.map((point) => [Number(point.lat), Number(point.lon)] as [number, number]).filter(
      ([lat, lon]) => hasFiniteLatLon(lat, lon)
    ) ?? [];

  if (fromPath.length > 1) {
    return fromPath;
  }

  if (leg.from_coord && leg.to_coord) {
    const fallback = [
      [Number(leg.from_coord.lat), Number(leg.from_coord.lon)] as [number, number],
      [Number(leg.to_coord.lat), Number(leg.to_coord.lon)] as [number, number]
    ].filter(([lat, lon]) => hasFiniteLatLon(lat, lon));
    if (fallback.length === 2) {
      return fallback;
    }
  }

  if (leg.geometry?.type === 'LineString' && Array.isArray(leg.geometry.coordinates)) {
    const fromGeometry = leg.geometry.coordinates
      .map(([lon, lat]) => [Number(lat), Number(lon)] as [number, number])
      .filter(([lat, lon]) => hasFiniteLatLon(lat, lon));
    if (fromGeometry.length > 1) {
      return fromGeometry;
    }
    if (fromGeometry.length === 1) {
      return [fromGeometry[0], fromGeometry[0]];
    }
  }

  if (fromPath.length === 1) {
    return [fromPath[0], fromPath[0]];
  }

  return [];
};

const RouteMap: React.FC<RouteMapProps> = ({ legs }) => {
  const { bounds, polylines, startPoint, endPoint } = useMemo(() => {
    const pathGroups = legs.map((leg) => normaliseLegPath(leg)).filter((points) => points.length > 0);
    const allPoints = pathGroups.flat();
    if (allPoints.length === 0) {
      return {
        bounds: null,
        polylines: [] as [number, number][][],
        startPoint: null,
        endPoint: null
      };
    }

    const lats = allPoints.map((point) => point[0]);
    const lons = allPoints.map((point) => point[1]);
    const minLat = Math.min(...lats);
    const maxLat = Math.max(...lats);
    const minLon = Math.min(...lons);
    const maxLon = Math.max(...lons);

    return {
      bounds: [
        [minLat, minLon],
        [maxLat, maxLon]
      ] as LatLngBoundsExpression,
      polylines: pathGroups,
      startPoint: pathGroups[0]?.[0] ?? null,
      endPoint: pathGroups[pathGroups.length - 1]?.slice(-1)[0] ?? null
    };
  }, [legs]);

  return (
    <div className="overflow-hidden rounded-3xl border border-white/10 shadow-inner shadow-black/30">
      {polylines.length === 0 || !bounds ? (
        <div className="flex h-80 items-center justify-center bg-slate-900/60 text-sm text-slate-400">
          ルート情報が読み込めませんでした
        </div>
      ) : (
        <MapContainer
          key={legs.length}
          className="h-80 w-full"
          zoom={12}
          center={startPoint ?? [33.59, 130.40]}
          zoomControl={false}
          scrollWheelZoom={false}
          attributionControl
        >
          <TileLayer
            url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
          />
          <FitBounds bounds={bounds} />
          {polylines.map((polyline, index) => (
            <Polyline
              key={`leg-${index}`}
              positions={polyline}
              pathOptions={{
                color: colors[index % colors.length],
                weight: 5,
                opacity: 0.85,
                lineCap: 'round',
                lineJoin: 'round'
              }}
            />
          ))}
          {startPoint && (
            <CircleMarker
              center={startPoint}
              pathOptions={{ color: '#22d3ee', fillColor: '#22d3ee' }}
              radius={8}
              weight={1.5}
            />
          )}
          {endPoint && (
            <CircleMarker
              center={endPoint}
              pathOptions={{ color: '#f97316', fillColor: '#f97316' }}
              radius={8}
              weight={1.5}
            />
          )}
        </MapContainer>
      )}
    </div>
  );
};

export default RouteMap;

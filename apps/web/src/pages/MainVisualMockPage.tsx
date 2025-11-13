import { useMemo, useState } from 'react';
import L from 'leaflet';
import { MapContainer, Marker, TileLayer, Polyline } from 'react-leaflet';

type StopPoint = {
  name: string;
  coord: [number, number];
};

const initialStops: StopPoint[] = [
  { name: '志賀島', coord: [33.6645246, 130.3077587] },
  { name: '和白丘', coord: [33.6984391, 130.4364629] },
  { name: '蒲田', coord: [33.6454639, 130.488794] },
  { name: '吉塚', coord: [33.6063776, 130.4234473] },
  { name: '天神', coord: [33.5892587, 130.3928265] },
  { name: '博多駅', coord: [33.590682, 130.4198639] },
  { name: '片江', coord: [33.5500743, 130.3729651] },
  { name: '椎葉', coord: [33.4678735, 130.3561294] },
  { name: '金武', coord: [33.5266618, 130.3144346] },
  { name: '元岡', coord: [33.5984081, 130.2266234] },
  { name: '宮浦', coord: [33.6466767, 130.2285863] }
];

const highlightItems = [
  '東西南北終点制覇',
  '最長距離乗車ルート',
  '搭乗路線数最大化',
  '一周チャレンジ自動生成'
];

const MainVisualMockPage: React.FC = () => {
  const [stops, setStops] = useState<StopPoint[]>(initialStops);

  const stopIcon = useMemo(
    () =>
      L.divIcon({
        html: '<div class="h-4 w-4 rounded-full bg-amber-400 border border-amber-500 shadow-lg shadow-amber-500/30"></div>',
        className: '',
        iconSize: [16, 16],
        iconAnchor: [8, 8]
      }),
    []
  );

  const routePath = useMemo<[number, number][]>(
    () => {
      if (stops.length < 2) {
        return [];
      }
      const points: [number, number][] = [];
      const n = stops.length;
      for (let i = 0; i < n; i++) {
        const p0 = stops[i].coord;
        const p3 = stops[(i + 1) % n].coord;
        const prev = stops[(i - 1 + n) % n].coord;
        const next = stops[(i + 2) % n].coord;
        const scale = 0.25;
        const p1: [number, number] = [
          p0[0] + (p3[0] - prev[0]) * scale,
          p0[1] + (p3[1] - prev[1]) * scale
        ];
        const p2: [number, number] = [
          p3[0] - (next[0] - p0[0]) * scale,
          p3[1] - (next[1] - p0[1]) * scale
        ];
        const steps = 24;
        for (let step = 0; step <= steps; step += 1) {
          const t = step / steps;
          const mt = 1 - t;
          const mt2 = mt * mt;
          const t2 = t * t;
          const a = mt2 * mt;
          const b = 3 * mt2 * t;
          const c = 3 * mt * t2;
          const d = t * t2;
          const lat = a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0];
          const lon = a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1];
          points.push([lat, lon]);
        }
      }
      return points;
    },
    [stops]
  );

  const mapBounds = useMemo(() => {
    const lats = stops.map((stop) => stop.coord[0]);
    const lons = stops.map((stop) => stop.coord[1]);
    return {
      minLat: Math.min(...lats),
      maxLat: Math.max(...lats),
      minLon: Math.min(...lons),
      maxLon: Math.max(...lons)
    };
  }, [stops]);

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 px-6 py-8 text-white">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-10 lg:flex-row">
        <div className="flex-1 space-y-6">
          <div className="inline-flex items-center gap-3 rounded-full bg-white/10 px-4 py-2 text-xs uppercase tracking-[0.25em] text-slate-100">
            <span>バス社会</span>
            <span className="text-slate-400">福岡</span>
          </div>
          <div className="space-y-3">
            <h1 className="text-4xl font-semibold leading-tight text-white md:text-5xl">
              reRoute Fukuoka
              <br />
            </h1>
            <p className="max-w-xl text-lg text-slate-300">
              Mixway の時刻表データをベースに、博多駅発のバスチャレンジを AI が即時計算。
            </p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {highlightItems.map((item) => (
              <div
                key={item}
                className="rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-medium text-slate-100 shadow-lg shadow-black/20"
              >
                {item}
              </div>
            ))}
          </div>
          <div className="flex items-center gap-4 rounded-2xl border border-amber-300/40 bg-amber-400/20 px-4 py-3 text-amber-100 shadow-lg shadow-amber-500/25">
            <div className="flex h-14 w-14 items-center justify-center rounded-full bg-amber-400/80 text-slate-950">
              AI
            </div>
            <div>
              <p className="text-sm uppercase tracking-[0.3em] text-amber-200">reRoute Fukuoka</p>
              <p className="text-lg font-semibold text-white">AI で算出されたチャレンジプラン</p>
            </div>
          </div>
        </div>
        <div className="relative flex-1">
          <div className="relative h-[640px] overflow-hidden rounded-3xl border border-white/10 bg-slate-950 shadow-[0_30px_60px_-35px_rgba(15,23,42,0.9)]">
            <MapContainer
              bounds={[
                [mapBounds.minLat - 0.04, mapBounds.minLon - 0.05],
                [mapBounds.maxLat + 0.04, mapBounds.maxLon + 0.05]
              ]}
              className="h-full w-full"
              zoomControl
              attributionControl={false}
              scrollWheelZoom
              doubleClickZoom
            >
              <TileLayer url="https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png" />
              {routePath.length > 0 && (
                <Polyline
                  positions={routePath}
                  pathOptions={{
                    color: '#fb7185',
                    weight: 5,
                    opacity: 0.9,
                    lineCap: 'round',
                    lineJoin: 'round'
                  }}
                />
              )}
              {stops.map(({ name, coord }, index) => (
                <Marker
                  key={name}
                  position={coord}
                  icon={stopIcon}
                  draggable
                  eventHandlers={{
                    drag: (event) => {
                      const marker = event.target;
                      const { lat, lng } = marker.getLatLng();
                      setStops((prev) =>
                        prev.map((stop, idx) =>
                          idx === index ? { ...stop, coord: [lat, lng] } : stop
                        )
                      );
                    },
                    dragend: (event) => {
                      const marker = event.target;
                      const { lat, lng } = marker.getLatLng();
                      setStops((prev) =>
                        prev.map((stop, idx) =>
                          idx === index ? { ...stop, coord: [lat, lng] } : stop
                        )
                      );
                    }
                  }}
                />
              ))}
            </MapContainer>
            <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-slate-950 via-transparent to-transparent pb-6 pt-12" />
            <div className="absolute bottom-6 right-6 flex max-w-[240px] flex-col gap-2 rounded-2xl border border-white/10 bg-white/10 p-4 text-xs text-slate-100 backdrop-blur-md">
              <p className="text-sm font-semibold text-white">AI チャレンジ生成（モック）</p>
              <p>
                志賀島から宮浦まで指定されたチェックポイントを接続したサンプルルートです。実際の経路探索が完成したら、このビジュアルに RAPTOR
                で求めた本物のチャレンジを重ねます。
              </p>
            </div>
            <div className="absolute left-6 top-6 rounded-full border border-white/20 bg-white/10 px-4 py-1 text-xs uppercase tracking-[0.4em] text-white">
              Fukuoka City Mock Route
            </div>
          </div>
          <div className="mt-4 text-right text-xs text-slate-400">
            ※ 現在はモックデータを使用。実際の経路計算が仕上がり次第、同じ UI で差し替え予定です。
          </div>
        </div>
      </div>
    </div>
  );
};

export default MainVisualMockPage;

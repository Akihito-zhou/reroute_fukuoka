import { motion } from 'framer-motion';
import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import RouteMap from '../components/RouteMap';
import { ChallengeDetail } from '../types/challenge';

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? 'http://localhost:8000/api/v1';

const ChallengeDetailPage: React.FC = () => {
  const { challengeId } = useParams<{ challengeId: string }>();
  const [detail, setDetail] = useState<ChallengeDetail | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!challengeId) {
      return;
    }
    const controller = new AbortController();
    async function load() {
      setLoading(true);
      setError(null);
      setDetail(null);
      try {
        const response = await fetch(`${API_BASE_URL}/challenges/${challengeId}`, {
          signal: controller.signal
        });
        if (!response.ok) {
          throw new Error(`Failed to fetch challenge ${challengeId}`);
        }
        const payload = (await response.json()) as ChallengeDetail;
        setDetail(payload);
      } catch (err) {
        if (!(err instanceof DOMException && err.name === 'AbortError')) {
          setError('チャレンジ詳細の取得に失敗しました。トップに戻ってやり直してください。');
        }
      } finally {
        setLoading(false);
      }
    }

    void load();
    return () => controller.abort();
  }, [challengeId]);

  const summaryStats = useMemo(() => {
    if (!detail) {
      return [];
    }
    return [
      {
        label: '総乗車時間',
        value: `${detail.total_ride_minutes} 分`,
        sub: `${Math.floor(detail.total_ride_minutes / 60)} 時間 ${detail.total_ride_minutes % 60} 分`,
        accent: 'text-cyan-200'
      },
      {
        label: '想定距離',
        value: `${detail.total_distance_km.toFixed(1)} km`,
        sub: '概算（直線距離換算）',
        accent: 'text-indigo-200'
      },
      {
        label: '乗り継ぎ回数',
        value: `${detail.transfers} 回`,
        sub: detail.transfers > 0 ? '乗り継ぎもチャレンジのうち' : '直行ルート',
        accent: 'text-emerald-200'
      },
      {
        label: 'エリア',
        value: detail.wards.join(' / ') || '福岡市内',
        sub: '広がりを体感しよう',
        accent: 'text-pink-200'
      }
    ];
  }, [detail]);

  const lastArrival = useMemo(() => {
    if (!detail || detail.legs.length === 0) {
      return '--:--';
    }
    return detail.legs[detail.legs.length - 1].arrival;
  }, [detail]);

  return (
    <div className="relative min-h-screen overflow-hidden bg-[#060a18] text-slate-100">
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute -top-48 right-[-120px] h-[520px] w-[520px] rounded-full bg-cyan-500/25 blur-[160px]" />
        <div className="absolute bottom-[-200px] left-[-100px] h-[460px] w-[460px] rounded-full bg-purple-500/25 blur-[160px]" />
      </div>

      <main className="relative mx-auto flex min-h-screen w-full max-w-5xl flex-col gap-10 px-6 pb-16 pt-14 md:px-10 lg:px-12">
        <div className="flex items-center justify-between">
          <Link
            to="/"
            className="inline-flex items-center gap-2 rounded-2xl border border-white/20 bg-white/10 px-4 py-2 text-sm font-semibold text-white transition hover:border-white/40 hover:bg-white/20"
          >
            ← 一覧に戻る
          </Link>
          {detail && (
            <span className="rounded-full border border-white/20 bg-white/10 px-4 py-1 text-xs font-semibold uppercase tracking-[0.4em] text-cyan-100">
              {detail.start_time} START
            </span>
          )}
        </div>

        {error && (
          <div className="rounded-3xl border border-red-400/40 bg-red-500/10 px-4 py-4 text-sm text-red-100">
            {error}
          </div>
        )}

        {loading ? (
          <div className="space-y-6">
            <div className="h-40 rounded-3xl border border-white/10 bg-white/[0.08] animate-pulse" />
            <div className="h-80 rounded-3xl border border-white/10 bg-white/[0.06] animate-pulse" />
            <div className="h-96 rounded-3xl border border-white/10 bg-white/[0.04] animate-pulse" />
          </div>
        ) : (
          detail && (
            <>
              <section className="space-y-6 rounded-3xl border border-white/10 bg-white/[0.05] p-8 shadow-xl shadow-black/30 backdrop-blur-md md:p-10">
                <div className="flex flex-col gap-6 md:flex-row md:items-start md:justify-between">
                  <div className="space-y-3">
                    <p className="text-sm font-semibold uppercase tracking-[0.4em] text-cyan-200">
                      {detail.badges.join('・') || 'FEATURED ROUTE'}
                    </p>
                    <h1 className="text-3xl font-semibold leading-tight text-white md:text-4xl">
                      {detail.title}
                    </h1>
                    <p className="max-w-2xl text-base leading-relaxed text-slate-200 md:text-lg">
                      {detail.tagline}
                    </p>
                    <p className="inline-flex items-center gap-2 rounded-full bg-black/40 px-3 py-1 text-xs text-slate-200">
                      出発停留所: <span className="font-semibold text-white">{detail.start_stop}</span>
                    </p>
                  </div>
                  <div className="grid gap-3 text-right text-xs text-slate-300">
                    {detail.theme_tags.map((tag) => (
                      <span key={tag} className="rounded-full bg-white/10 px-4 py-1 font-semibold text-white">
                        #{tag}
                      </span>
                    ))}
                  </div>
                </div>

                <div className="grid gap-4 rounded-3xl bg-black/30 p-4 sm:grid-cols-2 lg:grid-cols-4">
                  {summaryStats.map((stat) => (
                    <div
                      key={stat.label}
                      className="flex flex-col justify-between rounded-2xl bg-white/5 px-4 py-5 text-sm"
                    >
                      <p className="font-semibold uppercase tracking-[0.3em] text-slate-200">{stat.label}</p>
                      <p className={`mt-3 text-2xl font-semibold text-white ${stat.accent}`}>{stat.value}</p>
                      <p className="mt-1 text-[11px] uppercase tracking-[0.25em] text-slate-400">{stat.sub}</p>
                    </div>
                  ))}
                </div>
              </section>

              <section className="space-y-4">
                <h2 className="text-lg font-semibold uppercase tracking-[0.3em] text-slate-200">
                  ルートマップ
                </h2>
                <RouteMap legs={detail.legs} />
              </section>

              <section className="space-y-5 rounded-3xl border border-white/10 bg-white/[0.03] p-6 shadow-lg shadow-black/20 md:p-8">
                <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
                  <div>
                    <h2 className="text-lg font-semibold uppercase tracking-[0.3em] text-slate-200">
                      行程タイムライン
                    </h2>
                    <p className="text-sm text-slate-300">
                      24 時間の中で {detail.legs.length} 区間をバトンのように乗り継ぎます。
                    </p>
                  </div>
                  <p className="rounded-full bg-white/10 px-4 py-1 text-xs text-slate-200">
                    Start {detail.start_time} → 最終到着 {lastArrival}
                  </p>
                </div>
                <div className="space-y-4">
                  {detail.legs.map((leg) => (
                    <motion.article
                      key={`${detail.id}-${leg.sequence}`}
                      initial={{ opacity: 0, x: -12 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: leg.sequence * 0.04 }}
                      className="grid items-center gap-4 rounded-3xl border border-white/10 bg-black/30 p-4 sm:grid-cols-[auto,1fr] sm:p-5"
                    >
                      <div className="flex flex-col items-center justify-center">
                        <span className="text-xs font-semibold uppercase tracking-[0.4em] text-cyan-200">
                          Leg
                        </span>
                        <span className="mt-1 text-2xl font-semibold text-white">
                          {leg.sequence.toString().padStart(2, '0')}
                        </span>
                      </div>
                      <div className="space-y-2">
                        <div className="flex flex-wrap items-center gap-3 text-xs text-slate-300">
                          <span className="rounded-full bg-white/10 px-3 py-1 font-semibold text-cyan-100">
                            {leg.departure} → {leg.arrival}
                          </span>
                          <span className="rounded-full bg-white/10 px-3 py-1 font-semibold text-indigo-100">
                            乗車 {leg.ride_minutes} 分
                          </span>
                          <span className="rounded-full bg-white/10 px-3 py-1 font-semibold text-emerald-100">
                            約 {leg.distance_km.toFixed(1)} km
                          </span>
                        </div>
                        <h3 className="text-lg font-semibold text-white">
                          {leg.line_label} {leg.line_name}
                        </h3>
                        <p className="text-sm text-slate-200">
                          {leg.from_stop} → {leg.to_stop}
                        </p>
                        {leg.notes.length > 0 && (
                          <div className="flex flex-wrap gap-2 text-xs text-slate-300">
                            {leg.notes.map((note) => (
                              <span key={note} className="rounded-full bg-white/10 px-3 py-1">
                                {note}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    </motion.article>
                  ))}
                </div>
              </section>

              {detail.rest_stops.length > 0 && (
                <section className="space-y-5 rounded-3xl border border-white/10 bg-emerald-500/10 p-6 text-emerald-50 shadow-lg shadow-emerald-500/20 md:p-8">
                  <h2 className="text-lg font-semibold uppercase tracking-[0.3em] text-emerald-200">
                    途中の休憩ポイント
                  </h2>
                  <div className="grid gap-4 sm:grid-cols-2">
                    {detail.rest_stops.map((rest) => (
                      <div
                        key={`${detail.id}-${rest.at}-${rest.minutes}`}
                        className="rounded-3xl bg-white/10 px-4 py-5 text-sm leading-relaxed shadow-inner shadow-emerald-400/20"
                      >
                        <p className="text-xs font-semibold uppercase tracking-[0.3em] text-emerald-200">
                          {rest.at}
                        </p>
                        <p className="mt-2 text-lg font-semibold text-white">{rest.minutes} 分の余裕</p>
                        <p className="mt-2 text-sm text-emerald-50">{rest.suggestion}</p>
                      </div>
                    ))}
                  </div>
                </section>
              )}
            </>
          )
        )}

        {!loading && !detail && !error && (
          <div className="rounded-3xl border border-white/20 bg-white/5 px-6 py-8 text-center text-sm text-slate-200">
            チャレンジを読み込めませんでした。トップページから選び直してください。
          </div>
        )}
      </main>
    </div>
  );
};

export default ChallengeDetailPage;

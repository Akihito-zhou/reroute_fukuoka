import { AnimatePresence, motion } from 'framer-motion';
import { useCallback, useEffect, useMemo, useState } from 'react';

type ChallengeSummary = {
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

type RestStop = {
  at: string;
  minutes: number;
  suggestion: string;
};

type Leg = {
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
};

type ChallengeDetail = ChallengeSummary & {
  legs: Leg[];
  rest_stops: RestStop[];
};

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? 'http://localhost:8000/api/v1';

const shimmerVariants = {
  initial: { opacity: 0, scale: 0.98 },
  animate: {
    opacity: 1,
    scale: 1,
    transition: { duration: 0.6, ease: 'easeOut' }
  }
};

const cardVariants = {
  hidden: { opacity: 0, y: 24, scale: 0.98 },
  visible: (i: number) => ({
    opacity: 1,
    y: 0,
    scale: 1,
    transition: { delay: 0.08 * i, duration: 0.6, ease: 'easeOut' }
  })
};

const detailVariants = {
  hidden: { opacity: 0, y: 32 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.45, ease: 'easeOut' }
  },
  exit: {
    opacity: 0,
    y: 20,
    transition: { duration: 0.25, ease: 'easeIn' }
  }
};

const App: React.FC = () => {
  const [challengeSummaries, setChallengeSummaries] = useState<ChallengeSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ChallengeDetail | null>(null);
  const [activeTag, setActiveTag] = useState<string | null>(null);
  const [loadingSummaries, setLoadingSummaries] = useState<boolean>(true);
  const [loadingDetail, setLoadingDetail] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    async function loadSummaries() {
      setLoadingSummaries(true);
      setError(null);
      try {
        const response = await fetch(`${API_BASE_URL}/challenges`, { signal: controller.signal });
        if (!response.ok) {
          throw new Error(`Failed to load challenges: ${response.status}`);
        }
        const payload = (await response.json()) as ChallengeSummary[];
        setChallengeSummaries(payload);
        if (payload.length > 0) {
          setSelectedId((current) => current ?? payload[0].id);
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') {
          return;
        }
        setError('チャレンジ情報の取得に失敗しました。時間をおいて再度お試しください。');
      } finally {
        setLoadingSummaries(false);
      }
    }

    void loadSummaries();
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (challengeSummaries.length === 0) {
      return;
    }
    const exists = challengeSummaries.some((challenge) => challenge.id === selectedId);
    if (!exists) {
      setSelectedId(challengeSummaries[0].id);
    }
  }, [challengeSummaries, selectedId]);

  const fetchDetail = useCallback(async (id: string) => {
    setLoadingDetail(true);
    setError(null);
    setDetail(null);
    try {
      const response = await fetch(`${API_BASE_URL}/challenges/${id}`);
      if (!response.ok) {
        throw new Error(`Failed to load challenge ${id}: ${response.status}`);
      }
      const payload = (await response.json()) as ChallengeDetail;
      setDetail(payload);
    } catch (err) {
      setError('詳細データの取得に失敗しました。リロードしてください。');
    } finally {
      setLoadingDetail(false);
    }
  }, []);

  useEffect(() => {
    if (!selectedId) {
      return;
    }
    void fetchDetail(selectedId);
  }, [fetchDetail, selectedId]);

  const themeTags = useMemo(() => {
    const tags = new Set<string>();
    challengeSummaries.forEach((challenge) => {
      challenge.theme_tags.forEach((tag) => tags.add(tag));
    });
    return Array.from(tags);
  }, [challengeSummaries]);

  const filteredChallenges = useMemo(() => {
    if (!activeTag) {
      return challengeSummaries;
    }
    return challengeSummaries.filter((challenge) => challenge.theme_tags.includes(activeTag));
  }, [activeTag, challengeSummaries]);

  return (
    <div className="min-h-screen bg-transparent">
      <div className="absolute inset-0 overflow-hidden">
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 0.4 }}
          transition={{ duration: 1.2 }}
          className="pointer-events-none absolute -top-32 right-0 h-[520px] w-[520px] rounded-full bg-cyan-500/40 blur-[120px]"
        />
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 0.35 }}
          transition={{ delay: 0.4, duration: 1.2 }}
          className="pointer-events-none absolute bottom-[-200px] left-[-120px] h-[600px] w-[600px] rounded-full bg-purple-500/30 blur-[140px]"
        />
      </div>

      <main className="relative mx-auto flex min-h-screen max-w-6xl flex-col gap-12 px-6 pb-20 pt-16 md:px-10 lg:px-16">
        <motion.section
          variants={shimmerVariants}
          initial="initial"
          animate="animate"
          className="space-y-6 rounded-3xl border border-white/10 bg-white/5 p-8 shadow-2xl backdrop-blur-md md:p-12"
        >
          <p className="inline-flex items-center gap-2 rounded-full bg-indigo-500/20 px-4 py-1 text-sm font-semibold text-indigo-200">
            博多スタート固定
          </p>
          <h1 className="text-3xl font-bold leading-tight text-white md:text-4xl lg:text-5xl">
            reRoute FUKUOKA — 乗り放題×AIで挑む
          </h1>
          <p className="max-w-3xl text-lg leading-relaxed text-slate-200 md:text-xl">
            博多駅を起点に、AI が 24 時間以内で「最長乗車時間」「最多ユニーク停留所」「福岡市一周」の
            3 大チャレンジルートを自動生成します。人力では組めない乗り継ぎを、福岡市内フリーパスだけでどこまで走破できるか試してみましょう。
          </p>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setActiveTag(null)}
              className={`rounded-full border px-3 py-1 text-sm transition ${
                activeTag === null
                  ? 'border-indigo-300 bg-indigo-400/60 text-slate-900'
                  : 'border-white/20 bg-white/5 text-slate-200 hover:border-indigo-200/40'
              }`}
            >
              全チャレンジ
            </button>
            {themeTags.map((tag) => (
              <button
                key={tag}
                type="button"
                onClick={() => setActiveTag((prev) => (prev === tag ? null : tag))}
                className={`rounded-full border px-3 py-1 text-sm transition ${
                  activeTag === tag
                    ? 'border-cyan-300 bg-cyan-300/75 text-slate-900'
                    : 'border-white/20 bg-white/5 text-slate-200 hover:border-cyan-200/40'
                }`}
              >
                {tag}
              </button>
            ))}
          </div>
        </motion.section>

        <section className="grid gap-6 lg:grid-cols-[1.3fr_1fr]">
          <div className="space-y-4">
            {error && (
              <div className="rounded-xl border border-red-500/40 bg-red-500/20 p-4 text-sm text-red-100">
                {error}
              </div>
            )}

            {loadingSummaries ? (
              <motion.div
                initial={{ opacity: 0.3 }}
                animate={{ opacity: 1 }}
                className="grid grid-cols-1 gap-4 md:grid-cols-2"
              >
                {Array.from({ length: 4 }).map((_, index) => (
                  <div
                    key={`skeleton-${index}`}
                    className="h-44 rounded-2xl border border-white/10 bg-white/[0.08] animate-pulse"
                  />
                ))}
              </motion.div>
            ) : (
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <AnimatePresence>
                  {filteredChallenges.map((challenge, index) => {
                    const isSelected = challenge.id === selectedId;
                    return (
                      <motion.button
                        key={challenge.id}
                        layout
                        custom={index}
                        variants={cardVariants}
                        initial="hidden"
                        animate="visible"
                        exit={{ opacity: 0, scale: 0.98 }}
                        type="button"
                        onClick={() => setSelectedId(challenge.id)}
                        className={`group flex h-full flex-col rounded-2xl border px-4 py-5 text-left transition focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900 ${
                          isSelected
                            ? 'border-cyan-300/70 bg-cyan-400/20 shadow-[0_20px_60px_-20px_rgba(6,182,212,0.6)]'
                            : 'border-white/10 bg-white/[0.05] hover:border-cyan-200/40 hover:bg-cyan-200/10'
                        }`}
                      >
                        <div className="mb-3 flex items-center justify-between">
                          <span className="text-xs font-semibold tracking-wide text-cyan-200">
                            {challenge.start_time} 発
                          </span>
                          <span className="text-xs font-semibold text-slate-300">
                            {challenge.badges.join('・') || '西鉄バス 市内限定'}
                          </span>
                        </div>
                        <h2 className="text-lg font-semibold text-white">{challenge.title}</h2>
                        <p className="mt-2 text-sm leading-relaxed text-slate-200">
                          {challenge.tagline}
                        </p>
                        <div className="mt-auto flex flex-wrap items-center gap-2 pt-4 text-xs text-slate-300">
                          <span className="inline-flex items-center gap-1 rounded-full bg-white/10 px-2 py-1 font-semibold text-cyan-100">
                            ⏱ {challenge.total_ride_minutes} 分
                          </span>
                          <span className="inline-flex items-center gap-1 rounded-full bg-white/10 px-2 py-1 font-semibold text-indigo-100">
                            🚍 {challenge.transfers} 回乗り継ぎ
                          </span>
                          <span className="inline-flex items-center gap-1 rounded-full bg-white/10 px-2 py-1 font-semibold text-pink-100">
                            📏 {challenge.total_distance_km.toFixed(1)} km
                          </span>
                        </div>
                      </motion.button>
                    );
                  })}
                </AnimatePresence>
              </div>
            )}
          </div>

          <div className="space-y-4">
            <AnimatePresence mode="wait">
              {detail && !loadingDetail ? (
                <motion.article
                  key={detail.id}
                  variants={detailVariants}
                  initial="hidden"
                  animate="visible"
                  exit="exit"
                  className="sticky top-10 rounded-3xl border border-white/10 bg-white/[0.08] p-6 shadow-2xl backdrop-blur"
                >
                  <div className="flex items-baseline justify-between gap-4">
                    <h3 className="text-2xl font-bold text-white">{detail.title}</h3>
                    <span className="text-sm font-semibold text-cyan-100">
                      博多駅前A スタート
                    </span>
                  </div>
                  <p className="mt-3 text-sm leading-relaxed text-slate-200">{detail.tagline}</p>

                  <div className="mt-6 grid grid-cols-2 gap-3 text-sm">
                    <div className="rounded-2xl bg-black/20 p-3">
                      <p className="text-xs text-slate-300">想定乗車時間</p>
                      <p className="mt-1 text-lg font-semibold text-cyan-100">
                        {detail.total_ride_minutes} 分
                      </p>
                    </div>
                    <div className="rounded-2xl bg-black/20 p-3">
                      <p className="text-xs text-slate-300">推定移動距離</p>
                      <p className="mt-1 text-lg font-semibold text-indigo-100">
                        {detail.total_distance_km.toFixed(1)} km
                      </p>
                    </div>
                    <div className="rounded-2xl bg-black/20 p-3">
                      <p className="text-xs text-slate-300">乗り継ぎ</p>
                      <p className="mt-1 text-lg font-semibold text-pink-100">
                        {detail.transfers} 回
                      </p>
                    </div>
                    <div className="rounded-2xl bg-black/20 p-3">
                      <p className="text-xs text-slate-300">通過エリア</p>
                      <p className="mt-1 text-sm text-slate-100">{detail.wards.join(' / ')}</p>
                    </div>
                  </div>

                  <div className="mt-6 space-y-4">
                    <h4 className="text-sm font-semibold uppercase tracking-[0.3em] text-cyan-200">
                      ルート詳細
                    </h4>
                    <div className="space-y-3">
                      {detail.legs.map((leg) => (
                        <motion.div
                          key={`${detail.id}-${leg.sequence}`}
                          initial={{ opacity: 0, x: -12 }}
                          animate={{ opacity: 1, x: 0 }}
                          transition={{ delay: leg.sequence * 0.05 }}
                          className="rounded-2xl border border-white/10 bg-black/20 p-3"
                        >
                          <div className="flex items-baseline justify-between gap-4">
                            <p className="text-xs font-semibold text-cyan-100">
                              #{leg.sequence.toString().padStart(2, '0')}
                            </p>
                            <p className="text-xs font-semibold text-slate-200">
                              {leg.departure} → {leg.arrival}
                            </p>
                          </div>
                          <p className="mt-1 text-base font-semibold text-white">
                            {leg.line_label} {leg.line_name}
                          </p>
                          <p className="mt-1 text-sm text-slate-200">
                            {leg.from_stop} → {leg.to_stop}
                          </p>
                          <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-300">
                            <span className="rounded-full bg-white/10 px-2 py-1">
                              乗車 {leg.ride_minutes} 分
                            </span>
                            <span className="rounded-full bg-white/10 px-2 py-1">
                              約 {leg.distance_km.toFixed(1)} km
                            </span>
                            {leg.notes.map((note) => (
                              <span key={note} className="rounded-full bg-white/10 px-2 py-1">
                                {note}
                              </span>
                            ))}
                          </div>
                        </motion.div>
                      ))}
                    </div>
                  </div>

                  <div className="mt-8 space-y-3">
                    <h4 className="text-sm font-semibold uppercase tracking-[0.3em] text-emerald-200">
                      途中下車のヒント
                    </h4>
                    <div className="space-y-2">
                      {detail.rest_stops.map((rest) => (
                        <div
                          key={`${detail.id}-${rest.at}`}
                          className="rounded-2xl border border-white/10 bg-emerald-400/10 p-3 text-sm text-emerald-100"
                        >
                          <p className="font-semibold">{rest.at}</p>
                          <p className="mt-1 text-xs text-emerald-100/80">
                            推奨滞在 {rest.minutes} 分
                          </p>
                          <p className="mt-2 text-sm text-emerald-50">{rest.suggestion}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                </motion.article>
              ) : (
                <motion.div
                  key="loading"
                  initial={{ opacity: 0.4 }}
                  animate={{ opacity: 1 }}
                  className="sticky top-10 rounded-3xl border border-white/10 bg-white/[0.05] p-6 text-sm text-slate-200"
                >
                  {loadingDetail ? 'ルート詳細を読み込み中です…' : 'チャレンジを選択してください。'}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </section>
      </main>
    </div>
  );
};

export default App;

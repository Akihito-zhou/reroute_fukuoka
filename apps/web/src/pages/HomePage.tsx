import { motion } from 'framer-motion';
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { ChallengeSummary } from '../types/challenge';

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, '') ?? 'http://localhost:8000/api/v1';

const cardVariants = {
  hidden: { opacity: 0, y: 28, scale: 0.96 },
  visible: (index: number) => ({
    opacity: 1,
    y: 0,
    scale: 1,
    transition: { delay: 0.06 * index, duration: 0.45, ease: 'easeOut' }
  })
};

const HomePage: React.FC = () => {
  const [summaries, setSummaries] = useState<ChallengeSummary[]>([]);
  const [activeTag, setActiveTag] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const response = await fetch(`${API_BASE_URL}/challenges`, { signal: controller.signal });
        if (!response.ok) {
          throw new Error(`Failed to load challenges: ${response.status}`);
        }
        const payload = (await response.json()) as ChallengeSummary[];
        setSummaries(payload);
      } catch (err) {
        if (!(err instanceof DOMException && err.name === 'AbortError')) {
          setError('チャレンジ一覧の取得に失敗しました。しばらく待って再度お試しください。');
        }
      } finally {
        setLoading(false);
      }
    }

    void load();
    return () => controller.abort();
  }, []);

  const themeTags = useMemo(() => {
    const allTags = new Set<string>();
    summaries.forEach((summary) => {
      summary.theme_tags.forEach((tag) => allTags.add(tag));
    });
    return Array.from(allTags);
  }, [summaries]);

  const filteredSummaries = useMemo(() => {
    if (!activeTag) {
      return summaries;
    }
    return summaries.filter((summary) => summary.theme_tags.includes(activeTag));
  }, [activeTag, summaries]);

  return (
    <div className="relative min-h-screen overflow-hidden bg-[#070c1a] text-slate-100">
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute -top-40 right-0 h-96 w-96 rounded-full bg-cyan-500/30 blur-[140px]" />
        <div className="absolute bottom-[-180px] left-[-140px] h-[420px] w-[420px] rounded-full bg-indigo-500/25 blur-[160px]" />
      </div>

      <div className="relative mx-auto flex min-h-screen w-full max-w-6xl flex-col gap-12 px-6 pb-20 pt-16 md:px-12 lg:px-16">
        <header className="space-y-6 rounded-3xl border border-white/10 bg-white/[0.04] p-8 shadow-2xl backdrop-blur-xl md:p-12">
          <p className="inline-flex items-center gap-2 rounded-full bg-cyan-500/20 px-4 py-1 text-sm font-semibold text-cyan-100">
            博多発 24 時間チャレンジ
          </p>
          <div className="space-y-3">
            <h1 className="text-3xl font-semibold leading-tight text-white md:text-4xl lg:text-5xl">
              Re:Route Fukuoka
            </h1>
            <p className="max-w-3xl text-base leading-relaxed text-slate-200 md:text-lg">
              AI が毎朝アップデートする、福岡市内フリーパスで挑む三つのチャレンジ。耐久ロングライド /
              停留所コンプリート / 市内一筆書き。あなたはどれに挑戦する？
            </p>
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setActiveTag(null)}
              className={`rounded-full border px-4 py-1.5 text-sm transition ${
                activeTag === null
                  ? 'border-white bg-white text-slate-900 shadow-lg shadow-white/40'
                  : 'border-white/20 bg-white/5 text-slate-200 hover:border-white/40'
              }`}
            >
              すべて
            </button>
            {themeTags.map((tag) => (
              <button
                key={tag}
                type="button"
                onClick={() => setActiveTag((prev) => (prev === tag ? null : tag))}
                className={`rounded-full border px-4 py-1.5 text-sm transition ${
                  activeTag === tag
                    ? 'border-cyan-300 bg-cyan-200 text-slate-900 shadow-lg shadow-cyan-300/40'
                    : 'border-white/20 bg-white/5 text-slate-200 hover:border-cyan-200/50 hover:text-white'
                }`}
              >
                {tag}
              </button>
            ))}
          </div>
        </header>

        <main className="flex-1">
          {error && (
            <div className="mb-6 rounded-2xl border border-red-400/40 bg-red-500/10 px-4 py-3 text-sm text-red-100">
              {error}
            </div>
          )}

          {loading ? (
            <div className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">
              {Array.from({ length: 3 }).map((_, index) => (
                <div
                  key={`skeleton-${index}`}
                  className="h-60 rounded-3xl border border-white/10 bg-white/5 animate-pulse"
                />
              ))}
            </div>
          ) : (
            <div className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">
              {filteredSummaries.map((summary, index) => (
                <motion.article
                  key={summary.id}
                  custom={index}
                  initial="hidden"
                  animate="visible"
                  variants={cardVariants}
                  className="group flex h-full flex-col rounded-3xl border border-white/10 bg-white/[0.06] p-6 shadow-lg shadow-black/20 transition hover:-translate-y-1 hover:border-cyan-300/70 hover:bg-white/10"
                >
                  <div className="flex items-center justify-between text-xs font-semibold text-slate-200">
                    <span className="rounded-full bg-black/30 px-2 py-1 text-[11px] uppercase tracking-wide text-cyan-200">
                      {summary.start_time} START
                    </span>
                    <span>{summary.badges.join('・') || 'Special route'}</span>
                  </div>
                  <h2 className="mt-4 text-xl font-semibold text-white">{summary.title}</h2>
                  <p className="mt-3 text-sm leading-relaxed text-slate-200">{summary.tagline}</p>
                  <div className="mt-5 grid grid-cols-2 gap-2 text-xs text-slate-200">
                    <div className="rounded-2xl bg-black/30 px-3 py-2">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-cyan-200">
                        乗車時間
                      </p>
                      <p className="mt-1 text-base font-semibold text-white">
                        {summary.total_ride_minutes} 分
                      </p>
                    </div>
                    <div className="rounded-2xl bg-black/30 px-3 py-2">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-indigo-200">
                        距離
                      </p>
                      <p className="mt-1 text-base font-semibold text-white">
                        {summary.total_distance_km.toFixed(1)} km
                      </p>
                    </div>
                    <div className="rounded-2xl bg-black/30 px-3 py-2">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-emerald-200">
                        乗り継ぎ
                      </p>
                      <p className="mt-1 text-base font-semibold text-white">
                        {summary.transfers} 回
                      </p>
                    </div>
                    <div className="rounded-2xl bg-black/30 px-3 py-2">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-pink-200">
                        カバーエリア
                      </p>
                      <p className="mt-1 text-sm font-semibold text-white">
                        {summary.wards.join(' / ') || '福岡市内'}
                      </p>
                    </div>
                  </div>

                  <div className="mt-auto pt-6">
                    <Link
                      to={`/challenge/${summary.id}`}
                      className="inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-gradient-to-r from-cyan-400 to-indigo-500 px-5 py-3 text-sm font-semibold text-slate-900 shadow-lg shadow-cyan-500/30 transition hover:brightness-110"
                    >
                      詳細をみる
                      <span aria-hidden="true">→</span>
                    </Link>
                  </div>
                </motion.article>
              ))}
            </div>
          )}
        </main>

        <footer className="pb-6 text-center text-xs text-slate-400">
          © {new Date().getFullYear()} reRoute Fukuoka
        </footer>
      </div>
    </div>
  );
};

export default HomePage;

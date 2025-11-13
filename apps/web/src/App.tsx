import { BrowserRouter, Route, Routes, useLocation } from 'react-router-dom';
import { useState, useEffect } from 'react';
import ChallengeDetailPage from './pages/ChallengeDetailPage';
import HomePage from './pages/HomePage';
import MainVisualMockPage from './pages/MainVisualMockPage';

// ローディング表示コンポーネント
const LoadingOverlay: React.FC = () => (
  <div className="fixed inset-0 flex items-center justify-center bg-white/80 z-50 text-xl font-semibold">
    計算中...
  </div>
);

const AppContent: React.FC = () => {
  const location = useLocation();
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // ページ遷移時にローディングを表示
    setLoading(true);
    const timer = setTimeout(() => setLoading(false), 800); // 擬似的なロード時間
    return () => clearTimeout(timer);
  }, [location]);

  return (
    <>
      {loading && <LoadingOverlay />}
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/challenge/:challengeId" element={<ChallengeDetailPage />} />
      </Routes>
    </>
  );
};

const App: React.FC = () => (
  <BrowserRouter>

    <AppContent />

  </BrowserRouter>
);

export default App;

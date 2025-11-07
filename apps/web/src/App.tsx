import { BrowserRouter, Route, Routes } from 'react-router-dom';
import ChallengeDetailPage from './pages/ChallengeDetailPage';
import HomePage from './pages/HomePage';
import MainVisualMockPage from './pages/MainVisualMockPage';

const App: React.FC = () => (
  <BrowserRouter>
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/challenge/:challengeId" element={<ChallengeDetailPage />} />
      <Route path="/mock/main-visual" element={<MainVisualMockPage />} />
    </Routes>
  </BrowserRouter>
);

export default App;

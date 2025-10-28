import { BrowserRouter, Route, Routes } from 'react-router-dom';
import ChallengeDetailPage from './pages/ChallengeDetailPage';
import HomePage from './pages/HomePage';

const App: React.FC = () => (
  <BrowserRouter>
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/challenge/:challengeId" element={<ChallengeDetailPage />} />
    </Routes>
  </BrowserRouter>
);

export default App;

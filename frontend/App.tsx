import React from 'react';
import { HashRouter as Router, Routes, Route } from 'react-router-dom';
import Navbar from './components/Navbar';
import LandingPage from './pages/LandingPage';
import CurrentMarkets from './pages/CurrentMarkets';
import PositiveEV from './pages/PositiveEV';
import Arbitrage from './pages/Arbitrage';

const App: React.FC = () => {
  return (
    <Router>
      <div className="min-h-screen bg-black text-zinc-100 font-sans selection:bg-amber-500 selection:text-black">
        <Navbar />
        <main>
          <Routes>
            <Route path="/" element={<LandingPage />} />
            <Route path="/markets" element={<CurrentMarkets />} />
            <Route path="/positive-ev" element={<PositiveEV />} />
            <Route path="/arbitrage" element={<Arbitrage />} />
            {/* Placeholders for future routes */}
            <Route path="/parlay" element={<div className="flex h-[80vh] items-center justify-center text-zinc-500">Parlay Builder Coming Soon</div>} />
          </Routes>
        </main>
      </div>
    </Router>
  );
};

export default App;

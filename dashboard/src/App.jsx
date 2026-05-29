import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import RunDetail from "./components/RunDetail";
import RunList from "./components/RunList";
import "./App.css";

function App() {
  return (
    <BrowserRouter>
      <div className="app-shell">
        <header className="topbar">
          <Link to="/" className="brand">
            RC Lead Pipeline
          </Link>
          <nav>
            <Link to="/">Runs</Link>
          </nav>
        </header>

        <main className="page">
          <Routes>
            <Route path="/" element={<RunList />} />
            <Route path="/run/:id" element={<RunDetail />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}

export default App;

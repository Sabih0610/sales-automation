import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom"
import Leads from "./pages/Leads"
import Campaigns from "./pages/Campaigns"
import Sequences from "./pages/Sequences"
import Runs from "./pages/Runs"
import Settings from "./pages/Settings"
import Dashboard from "./pages/Dashboard"
import RunDetail from "./pages/RunDetail"
import "./App.css"

export default function App() {
  return (
    <BrowserRouter>
      <div className="shell">
        <aside className="sidebar">
          <div className="brand">
            <div className="brand-name">RC Sales</div>
            <div className="brand-sub">Sales Automation Platform</div>
          </div>
          <nav className="nav">
            <div className="nav-section">Overview</div>
            <NavLink to="/" end className={({isActive})=>`nav-item${isActive?" active":""}`}>
              <i className="ti ti-layout-dashboard" aria-hidden="true" />
              Dashboard
            </NavLink>
            <div className="nav-section">Work</div>
            <NavLink to="/leads" className={({isActive})=>`nav-item${isActive?" active":""}`}>
              <i className="ti ti-users" aria-hidden="true" />
              Leads
            </NavLink>
            <NavLink to="/campaigns" className={({isActive})=>`nav-item${isActive?" active":""}`}>
              <i className="ti ti-speakerphone" aria-hidden="true" />
              Campaigns
            </NavLink>
            <NavLink to="/sequences" className={({isActive})=>`nav-item${isActive?" active":""}`}>
              <i className="ti ti-mail-forward" aria-hidden="true" />
              Sequences
            </NavLink>
            <NavLink to="/runs" className={({isActive})=>`nav-item${isActive?" active":""}`}>
              <i className="ti ti-player-play" aria-hidden="true" />
              Runs
            </NavLink>
            <div className="nav-section">System</div>
            <NavLink to="/settings" className={({isActive})=>`nav-item${isActive?" active":""}`}>
              <i className="ti ti-settings" aria-hidden="true" />
              Settings
            </NavLink>
          </nav>
          <div className="sidebar-footer">
            <div className="avatar-row">
              <div className="avatar-circle">RC</div>
              <div>
                <div className="avatar-name">Royal Cyber</div>
                <div className="avatar-role">Sales Team</div>
              </div>
            </div>
          </div>
        </aside>
        <div className="main">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/leads" element={<Leads />} />
            <Route path="/campaigns" element={<Campaigns />} />
            <Route path="/sequences" element={<Sequences />} />
            <Route path="/runs" element={<Runs />} />
            <Route path="/runs/:id" element={<RunDetail />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </div>
      </div>
    </BrowserRouter>
  )
}

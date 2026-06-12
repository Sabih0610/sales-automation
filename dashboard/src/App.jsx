import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom"
import Campaigns from "./pages/Campaigns"
import CampaignDetail from "./pages/campaign/CampaignDetail"
import RunDetailView from "./pages/campaign/RunDetailView"
import Settings from "./pages/Settings"
import Dashboard from "./pages/Dashboard"
import SystemHealthBar from "./components/SystemHealthBar"
import { ToastProvider } from "./components/ToastProvider"
import "./App.css"

export default function App() {
  return (
    <BrowserRouter>
      <ToastProvider>
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
              <NavLink to="/campaigns" className={({isActive})=>`nav-item${isActive?" active":""}`}>
                <i className="ti ti-speakerphone" aria-hidden="true" />
                Campaigns
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
            <SystemHealthBar />
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/campaigns" element={<Campaigns />} />
              <Route path="/campaigns/:filename/runs/:runId" element={<RunDetailView />} />
              <Route path="/campaigns/:filename/:tab?" element={<CampaignDetail />} />
              <Route path="/settings" element={<Settings />} />
            </Routes>
          </div>
        </div>
      </ToastProvider>
    </BrowserRouter>
  )
}

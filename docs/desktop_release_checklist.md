# Desktop Release Checklist

Use this checklist for Phase 6 Windows desktop builds.

## Before Building

- Confirm no real `.env` files are staged or included in release output.
- Confirm `dashboard/dist/` can be regenerated from current dashboard source.
- Confirm `dist/royal-cyber-backend/royal-cyber-backend.exe` is rebuilt from current backend source.
- Confirm local runtime data is outside the app folder under `%LOCALAPPDATA%\RoyalCyberLeadPipeline\`.
- Confirm Chrome/Sales Navigator still uses installed Chrome or `CHROME_PATH`.

## Build Commands

Run from the repository root unless noted:

```powershell
cd dashboard
npm run build
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_backend_exe.ps1
```

```powershell
cd desktop
npm run build:desktop
```

Or run the full release build from `desktop/`:

```powershell
npm run release
```

## Package Checks

- Installer appears in `desktop/release/`.
- Portable executable appears in `desktop/release/`.
- Packaged app contains the Electron app, `dashboard/dist/`, and `backend/royal-cyber-backend/`.
- Packaged app does not contain `.git`, real `.env`, development database files, output files, debug folders, or logs.
- Installed app opens without manually starting Python or Vite.
- Portable app opens without manually starting Python or Vite.
- Backend health responds at `http://127.0.0.1:8000/api/health`.
- Dashboard API requests return success.
- Closing the app stops only the backend process started by Electron.
- Starting Electron while a manual backend is already running reuses it and does not stop it on close.

## App-Data Checks

Confirm these paths are created under `%LOCALAPPDATA%\RoyalCyberLeadPipeline\`:

- `pipeline.db`
- `output\`
- `logs\`
- `chrome-scraper-profile\`
- `debug\`
- `.env` when user settings are saved

To reset desktop data, close the app and delete `%LOCALAPPDATA%\RoyalCyberLeadPipeline\`.
To back up desktop data, copy `pipeline.db*` and `output\` from that folder.

## Existing Workflow Checks

- `python main.py serve`
- `cd dashboard && npm run dev`
- `cd dashboard && npm run build`
- `cd desktop && npm run dev`
- `cd desktop && npm start`

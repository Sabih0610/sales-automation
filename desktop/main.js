const { app, BrowserWindow, dialog, shell } = require("electron")
const { spawn } = require("node:child_process")
const crypto = require("node:crypto")
const fs = require("node:fs")
const os = require("node:os")
const path = require("node:path")

const DASHBOARD_DEV_URL = process.env.RCLP_DASHBOARD_URL || "http://127.0.0.1:5173"
const DASHBOARD_DEV_ORIGIN = new URL(DASHBOARD_DEV_URL).origin
const BACKEND_HEALTH_URL = process.env.RCLP_BACKEND_HEALTH_URL || "http://127.0.0.1:8000/api/health"
const BACKEND_API_BASE = process.env.RCLP_API_BASE || "http://127.0.0.1:8000"
const BACKEND_WS_BASE = process.env.RCLP_WS_BASE || "ws://127.0.0.1:8000"
const BACKEND_START_TIMEOUT_MS = Number(process.env.RCLP_BACKEND_START_TIMEOUT_MS || 60000)
const PROJECT_ROOT = path.resolve(__dirname, "..")
const DESKTOP_MODE = (process.env.RCLP_DESKTOP_MODE || "built").trim().toLowerCase()
const APP_DATA_FOLDER_NAME = "RoyalCyberLeadPipeline"

let mainWindow = null
let backendProcess = null
let backendStartedByElectron = false
let backendStartupError = null
let backendReadyForDashboard = false
let backendFailureDetails = ""
let backendRuntimeDir = ""
let runtimeDashboardApiKey = ""
let stoppingBackend = false

function isDevDashboardMode() {
  return DESKTOP_MODE === "dev"
}

function isBuiltDashboardMode() {
  return !isDevDashboardMode()
}

function packagedResourcesRoot() {
  return app.isPackaged ? process.resourcesPath : PROJECT_ROOT
}

function dashboardDistIndexPath() {
  const configured = (process.env.RCLP_DASHBOARD_DIST_INDEX || "").trim()
  if (configured) {
    return configured
  }

  if (app.isPackaged) {
    return path.join(packagedResourcesRoot(), "dashboard", "dist", "index.html")
  }
  return path.join(PROJECT_ROOT, "dashboard", "dist", "index.html")
}

function packagedBackendExePath() {
  const configured = (process.env.RCLP_BACKEND_EXE || "").trim()
  if (configured) {
    return configured
  }

  if (app.isPackaged) {
    return path.join(
      packagedResourcesRoot(),
      "backend",
      "royal-cyber-backend",
      "royal-cyber-backend.exe",
    )
  }
  return path.join(
    PROJECT_ROOT,
    "dist",
    "royal-cyber-backend",
    "royal-cyber-backend.exe",
  )
}

function appIconPath() {
  const candidate = path.join(__dirname, "assets", "icon.ico")
  return fs.existsSync(candidate) ? candidate : undefined
}

function desktopAppDataDir() {
  if (process.env.APP_DATA_DIR && process.env.APP_DATA_DIR.trim()) {
    return path.resolve(process.env.APP_DATA_DIR.trim())
  }
  if (process.env.LOCALAPPDATA && process.env.LOCALAPPDATA.trim()) {
    return path.join(process.env.LOCALAPPDATA.trim(), APP_DATA_FOLDER_NAME)
  }
  if (process.platform === "win32") {
    return path.join(os.homedir(), "AppData", "Local", APP_DATA_FOLDER_NAME)
  }
  return path.join(os.homedir(), ".local", "share", APP_DATA_FOLDER_NAME)
}

function desktopRuntimePaths() {
  const appDataDir = desktopAppDataDir()
  const fromEnv = (name, fallback) => {
    const value = (process.env[name] || "").trim()
    if (!value) {
      return fallback
    }
    return path.isAbsolute(value) ? value : path.join(appDataDir, value)
  }

  const outputDir = fromEnv("OUTPUT_DIR", path.join(appDataDir, "output"))
  const logDir = fromEnv("LOG_DIR", path.join(appDataDir, "logs"))

  return {
    appDataDir,
    dbPath: fromEnv("DB_PATH", path.join(appDataDir, "pipeline.db")),
    outputDir,
    logDir,
    chromeProfileDir: fromEnv(
      "CHROME_PROFILE_DIR",
      path.join(appDataDir, "chrome-scraper-profile"),
    ),
    debugDir: fromEnv("DEBUG_DIR", path.join(appDataDir, "debug")),
    knowledgeBaseDir: fromEnv(
      "KNOWLEDGE_BASE_DIR",
      path.join(appDataDir, "knowledge_base"),
    ),
    envFile: path.join(appDataDir, ".env"),
    backendLogPath: path.join(logDir, "backend.log"),
  }
}

function desktopRuntimeEnv() {
  const runtimePaths = desktopRuntimePaths()
  return {
    RCLP_DESKTOP_MODE: "built",
    APP_DATA_DIR: runtimePaths.appDataDir,
    DB_PATH: runtimePaths.dbPath,
    OUTPUT_DIR: runtimePaths.outputDir,
    LOG_DIR: runtimePaths.logDir,
    CHROME_PROFILE_DIR: runtimePaths.chromeProfileDir,
    DEBUG_DIR: runtimePaths.debugDir,
    KNOWLEDGE_BASE_DIR: runtimePaths.knowledgeBaseDir,
  }
}

function ensureDesktopRuntimeDirs() {
  if (!isBuiltDashboardMode()) {
    return
  }

  const runtimePaths = desktopRuntimePaths()
  for (const directory of [
    runtimePaths.appDataDir,
    path.dirname(runtimePaths.dbPath),
    runtimePaths.outputDir,
    runtimePaths.logDir,
    runtimePaths.chromeProfileDir,
    runtimePaths.debugDir,
    runtimePaths.knowledgeBaseDir,
  ]) {
    fs.mkdirSync(directory, { recursive: true })
  }
}

function backendLogPath() {
  if (isBuiltDashboardMode()) {
    return desktopRuntimePaths().backendLogPath
  }
  return path.join(__dirname, "logs", "backend.log")
}

function appendDesktopLog(message) {
  const line = `[${new Date().toISOString()}] ${message}\n`
  try {
    const logPath = path.join(path.dirname(backendLogPath()), "desktop.log")
    fs.mkdirSync(path.dirname(logPath), { recursive: true })
    fs.appendFileSync(logPath, line)
  } catch {
    // Logging must never prevent app startup.
  }
}

process.on("uncaughtException", (error) => {
  appendDesktopLog(`Uncaught exception: ${error.stack || error.message || error}`)
})

process.on("unhandledRejection", (error) => {
  appendDesktopLog(`Unhandled rejection: ${error?.stack || error?.message || error}`)
})

appendDesktopLog(
  `Desktop main loaded. packaged=${app.isPackaged} resources=${process.resourcesPath || ""}`,
)

function isDashboardUrl(url) {
  try {
    const parsed = new URL(url)
    if (isDevDashboardMode()) {
      return parsed.origin === DASHBOARD_DEV_ORIGIN
    }
    return parsed.protocol === "file:"
  } catch {
    return false
  }
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function appendBackendLog(message) {
  const line = `[${new Date().toISOString()}] ${message}\n`
  try {
    const logPath = backendLogPath()
    fs.mkdirSync(path.dirname(logPath), { recursive: true })
    fs.appendFileSync(logPath, line)
  } catch (error) {
    console.error("Could not write backend log:", error)
  }
  console.log(line.trimEnd())
}

function appendBackendChunk(source, chunk) {
  const text = chunk.toString()
  for (const line of text.split(/\r?\n/)) {
    if (line.trim()) {
      appendBackendLog(`${source}: ${line}`)
    }
  }
}

function readDotEnvFileValue(envPath, name) {
  try {
    const content = fs.readFileSync(envPath, "utf8")
    for (const rawLine of content.split(/\r?\n/)) {
      const line = rawLine.trim()
      if (!line || line.startsWith("#")) {
        continue
      }
      const equalsIndex = line.indexOf("=")
      if (equalsIndex === -1) {
        continue
      }
      const key = line.slice(0, equalsIndex).trim()
      if (key !== name) {
        continue
      }
      let value = line.slice(equalsIndex + 1).trim()
      if (
        (value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'"))
      ) {
        value = value.slice(1, -1)
      }
      return value
    }
  } catch {
    return ""
  }
  return ""
}

function readDotEnvValue(name) {
  const envPaths = isBuiltDashboardMode()
    ? [desktopRuntimePaths().envFile, path.join(PROJECT_ROOT, ".env")]
    : [path.join(PROJECT_ROOT, ".env")]

  for (const envPath of envPaths) {
    const value = readDotEnvFileValue(envPath, name)
    if (value) {
      return value
    }
  }
  return ""
}

function dashboardApiKey() {
  const configuredKey = (
    process.env.RCLP_DASHBOARD_API_KEY ||
    process.env.DASHBOARD_API_KEY ||
    readDotEnvValue("DASHBOARD_API_KEY")
  ).trim()

  if (configuredKey) {
    return configuredKey
  }

  if (!runtimeDashboardApiKey) {
    runtimeDashboardApiKey = crypto.randomBytes(32).toString("base64url")
  }

  return runtimeDashboardApiKey
}

function backendLaunchConfig() {
  if (isDevDashboardMode()) {
    return {
      command: "python",
      args: ["main.py", "serve"],
      cwd: PROJECT_ROOT,
      label: "python main.py serve",
    }
  }

  const packagedBackendExe = packagedBackendExePath()
  if (!fs.existsSync(packagedBackendExe)) {
    throw new Error(
      `Packaged backend executable not found at ${packagedBackendExe}. Run "scripts\\build_backend_exe.ps1" first.`,
    )
  }

  let runtimeExe = packagedBackendExe
  const preparedRuntimeDir = process.env.RCLP_BACKEND_RUNTIME_DIR || ""
  if (preparedRuntimeDir) {
    backendRuntimeDir = preparedRuntimeDir
  } else {
    const sourceDir = path.dirname(packagedBackendExe)
    const runtimeBaseDir = fs.mkdtempSync(path.join(os.tmpdir(), "rclp-backend-"))
    const runtimeDir = path.join(runtimeBaseDir, "royal-cyber-backend")
    runtimeExe = path.join(runtimeDir, "royal-cyber-backend.exe")
    fs.cpSync(sourceDir, runtimeDir, { recursive: true })
    backendRuntimeDir = runtimeBaseDir
  }

  return {
    command: runtimeExe,
    args: [],
    cwd: app.isPackaged ? packagedResourcesRoot() : PROJECT_ROOT,
    label: runtimeExe,
  }
}

async function backendIsHealthy() {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 2000)
  try {
    const response = await fetch(BACKEND_HEALTH_URL, {
      cache: "no-store",
      signal: controller.signal,
    })
    return response.ok
  } catch {
    return false
  } finally {
    clearTimeout(timeout)
  }
}

function startBackendProcess() {
  ensureDesktopRuntimeDirs()
  const launch = backendLaunchConfig()
  appendBackendLog(`Starting backend from ${launch.cwd}: ${launch.label}`)
  backendStartupError = null
  backendStartedByElectron = true
  stoppingBackend = false
  const apiKey = dashboardApiKey()

  const backendEnv = {
    ...process.env,
    DASHBOARD_API_KEY: apiKey,
    PYTHONUNBUFFERED: "1",
  }
  if (isBuiltDashboardMode()) {
    Object.assign(backendEnv, desktopRuntimeEnv())
  }

  backendProcess = spawn(launch.command, launch.args, {
    cwd: launch.cwd,
    env: backendEnv,
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  })

  backendProcess.stdout.on("data", (chunk) => appendBackendChunk("stdout", chunk))
  backendProcess.stderr.on("data", (chunk) => appendBackendChunk("stderr", chunk))

  backendProcess.on("error", (error) => {
    backendStartupError = error
    appendBackendLog(`Backend process error: ${error.message}`)
  })

  backendProcess.on("exit", (code, signal) => {
    appendBackendLog(`Backend process exited with code ${code ?? "null"} and signal ${signal ?? "null"}`)
    if (backendRuntimeDir) {
      try {
        fs.rmSync(backendRuntimeDir, { recursive: true, force: true })
      } catch (error) {
        appendBackendLog(`Could not remove backend runtime directory ${backendRuntimeDir}: ${error.message}`)
      }
      backendRuntimeDir = ""
    }
    if (backendStartedByElectron && !stoppingBackend) {
      backendStartupError = new Error("The backend process exited before it became available.")
    }
  })
}

async function waitForBackend() {
  const deadline = Date.now() + BACKEND_START_TIMEOUT_MS
  while (Date.now() < deadline) {
    if (await backendIsHealthy()) {
      return true
    }
    if (backendStartupError) {
      throw backendStartupError
    }
    if (backendProcess && backendProcess.exitCode !== null) {
      return false
    }
    await delay(1000)
  }
  return false
}

async function ensureBackendReady() {
  if (await backendIsHealthy()) {
    appendBackendLog(`Existing backend is healthy at ${BACKEND_HEALTH_URL}; reusing it.`)
    return true
  }

  startBackendProcess()
  const ready = await waitForBackend()
  if (ready) {
    appendBackendLog(`Backend is healthy at ${BACKEND_HEALTH_URL}.`)
  }
  return ready
}

function stopBackendIfOwned() {
  if (!backendStartedByElectron || !backendProcess || backendProcess.exitCode !== null) {
    return
  }

  stoppingBackend = true
  const pid = backendProcess.pid
  appendBackendLog(`Stopping backend process ${pid}.`)
  backendStartedByElectron = false

  if (process.platform === "win32") {
    spawn("taskkill", ["/pid", String(pid), "/T", "/F"], {
      stdio: "ignore",
      windowsHide: true,
    })
    return
  }

  backendProcess.kill("SIGTERM")
}

function backendErrorHtml(details) {
  const escapeHtml = (value) => value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")

  const escapedDetails = details
    ? escapeHtml(details)
    : "Unknown backend startup error."
  const escapedHealthUrl = escapeHtml(BACKEND_HEALTH_URL)
  const escapedLogPath = escapeHtml(backendLogPath())

  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Backend could not start</title>
  <style>
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      background: #f8fafc;
      color: #0f172a;
      font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    main {
      max-width: 640px;
      padding: 32px;
      border: 1px solid #e2e8f0;
      border-radius: 10px;
      background: #ffffff;
      box-shadow: 0 18px 45px rgba(15, 23, 42, 0.08);
    }
    h1 {
      margin: 0 0 12px;
      font-size: 24px;
    }
    p {
      margin: 0 0 12px;
      line-height: 1.5;
      color: #475569;
    }
    code {
      color: #334155;
      word-break: break-word;
    }
  </style>
</head>
<body>
  <main>
    <h1>Local backend could not start</h1>
    <p>The desktop app could not start or reach the FastAPI backend at <code>${escapedHealthUrl}</code>.</p>
    <p>Try starting the backend manually from the project root with <code>python main.py serve</code>, then reopen the desktop app.</p>
    <p>Backend log: <code>${escapedLogPath}</code></p>
    <p><code>${escapedDetails}</code></p>
  </main>
</body>
</html>`
}

function createBackendErrorWindow(details) {
  mainWindow = new BrowserWindow({
    width: 920,
    height: 620,
    minWidth: 720,
    minHeight: 520,
    title: "Royal Cyber Lead Pipeline",
    icon: appIconPath(),
    backgroundColor: "#f8fafc",
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })
  mainWindow.on("closed", () => {
    mainWindow = null
  })
  mainWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(backendErrorHtml(details))}`)
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 960,
    minWidth: 1100,
    minHeight: 720,
    title: "Royal Cyber Lead Pipeline",
    icon: appIconPath(),
    backgroundColor: "#f8fafc",
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: !isBuiltDashboardMode(),
    },
  })
  mainWindow.on("closed", () => {
    mainWindow = null
  })

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (isDashboardUrl(url)) {
      return { action: "allow" }
    }
    shell.openExternal(url)
    return { action: "deny" }
  })

  mainWindow.webContents.on("will-navigate", (event, url) => {
    if (isDashboardUrl(url)) {
      return
    }
    event.preventDefault()
    shell.openExternal(url)
  })

  if (isDevDashboardMode()) {
    mainWindow.loadURL(DASHBOARD_DEV_URL)
    return
  }

  const dashboardDistIndex = dashboardDistIndexPath()
  if (!fs.existsSync(dashboardDistIndex)) {
    throw new Error(
      `Built dashboard not found at ${dashboardDistIndex}. Run "cd dashboard && npm run build" first.`,
    )
  }

  mainWindow.loadFile(dashboardDistIndex, {
    query: {
      apiBase: BACKEND_API_BASE,
      wsBase: BACKEND_WS_BASE,
      apiKey: dashboardApiKey(),
    },
  })
}

app.whenReady().then(async () => {
  try {
    ensureDesktopRuntimeDirs()
    const backendReady = await ensureBackendReady()
    if (!backendReady) {
      throw new Error(`Timed out waiting for ${BACKEND_HEALTH_URL}.`)
    }
    backendReadyForDashboard = true
    createWindow()
  } catch (error) {
    const details = error?.message || "Unknown backend startup error."
    backendFailureDetails = details
    appendBackendLog(`Backend startup failed: ${details}`)
    stopBackendIfOwned()
    dialog.showErrorBox(
      "Local backend could not start",
      `The desktop app could not start the local backend. Check ${backendLogPath()} for details.`,
    )
    createBackendErrorWindow(details)
  }

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      if (backendReadyForDashboard) {
        createWindow()
      } else {
        createBackendErrorWindow(backendFailureDetails)
      }
    }
  })
})

app.on("before-quit", () => {
  stopBackendIfOwned()
})

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit()
  }
})

const { spawn } = require("node:child_process")
const path = require("node:path")

const dashboardDir = path.resolve(__dirname, "..", "..", "dashboard")
const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm"

const env = {
  ...process.env,
  VITE_API_BASE: "http://127.0.0.1:8000",
  VITE_WS_BASE: "ws://127.0.0.1:8000",
  VITE_API_KEY: "",
}

const child = spawn(npmCommand, ["run", "build"], {
  cwd: dashboardDir,
  env,
  stdio: "inherit",
  windowsHide: false,
})

child.on("error", (error) => {
  console.error(error)
  process.exit(1)
})

child.on("exit", (code) => {
  process.exit(code ?? 0)
})

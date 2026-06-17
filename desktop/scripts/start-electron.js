const { spawn } = require("node:child_process")
const fs = require("node:fs")
const os = require("node:os")
const path = require("node:path")

const electronPath = require("electron")

const args = process.argv.slice(2)
const electronArgs = args.filter((arg) => !["--dev", "--built"].includes(arg))
const env = { ...process.env }
delete env.ELECTRON_RUN_AS_NODE

function prepareBackendRuntime() {
  const projectRoot = path.resolve(__dirname, "..", "..")
  const sourceExe = env.RCLP_BACKEND_EXE ||
    path.join(projectRoot, "dist", "royal-cyber-backend", "royal-cyber-backend.exe")

  if (!fs.existsSync(sourceExe)) {
    return
  }

  const runtimeBase = fs.mkdtempSync(path.join(os.tmpdir(), "rclp-backend-"))
  const runtimeDir = path.join(runtimeBase, "royal-cyber-backend")
  fs.cpSync(path.dirname(sourceExe), runtimeDir, { recursive: true })

  env.RCLP_BACKEND_EXE = path.join(runtimeDir, "royal-cyber-backend.exe")
  env.RCLP_BACKEND_RUNTIME_DIR = runtimeBase
}

if (args.includes("--dev")) {
  env.RCLP_DESKTOP_MODE = "dev"
}

if (args.includes("--built")) {
  env.RCLP_DESKTOP_MODE = "built"
  prepareBackendRuntime()
}

const child = spawn(electronPath, [...electronArgs, "."], {
  cwd: process.cwd(),
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

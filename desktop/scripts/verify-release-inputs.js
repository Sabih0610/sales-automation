const fs = require("node:fs")
const path = require("node:path")

const projectRoot = path.resolve(__dirname, "..", "..")

const requiredPaths = [
  {
    label: "dashboard production build",
    path: path.join(projectRoot, "dashboard", "dist", "index.html"),
    hint: "Run `cd dashboard && npm run build`.",
  },
  {
    label: "packaged backend executable",
    path: path.join(
      projectRoot,
      "dist",
      "royal-cyber-backend",
      "royal-cyber-backend.exe",
    ),
    hint: "Run `powershell -ExecutionPolicy Bypass -File scripts\\build_backend_exe.ps1`.",
  },
  {
    label: "desktop placeholder icon",
    path: path.join(projectRoot, "desktop", "assets", "icon.ico"),
    hint: "Restore `desktop/assets/icon.ico` or regenerate it from the project assets.",
  },
]

const missing = requiredPaths.filter((item) => !fs.existsSync(item.path))

if (missing.length) {
  console.error("Release build inputs are missing:")
  for (const item of missing) {
    console.error(`- ${item.label}: ${item.path}`)
    console.error(`  ${item.hint}`)
  }
  process.exit(1)
}

console.log("Release build inputs verified.")

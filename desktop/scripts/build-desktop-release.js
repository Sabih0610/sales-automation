const { spawnSync } = require("node:child_process")
const fs = require("node:fs")
const os = require("node:os")
const path = require("node:path")

const projectDir = path.resolve(__dirname, "..")
const releaseDir = path.join(projectDir, "release")
const targets = process.argv.slice(2)

if (!targets.length) {
  console.error("Usage: node scripts/build-desktop-release.js <nsis|portable> [...]")
  process.exit(1)
}

function electronBuilderCli() {
  return path.join(projectDir, "node_modules", "electron-builder", "cli.js")
}

function resetReleaseDir() {
  try {
    fs.rmSync(releaseDir, { recursive: true, force: true })
  } catch (error) {
    throw new Error(
      `Could not clean ${releaseDir}. Close any running packaged app and delete the folder, then retry. ${error.message}`,
    )
  }
  fs.mkdirSync(releaseDir, { recursive: true })
}

function copyReleaseArtifacts(tempOutputDir) {
  for (const entry of fs.readdirSync(tempOutputDir, { withFileTypes: true })) {
    if (!entry.isFile()) {
      continue
    }
    const source = path.join(tempOutputDir, entry.name)
    const target = path.join(releaseDir, entry.name)
    fs.copyFileSync(source, target)
  }
}

const tempBaseDir = fs.mkdtempSync(path.join(os.tmpdir(), "rclp-electron-builder-"))
const tempOutputDir = path.join(tempBaseDir, "release")
const args = [
  "--win",
  ...targets,
  `-c.directories.output=${tempOutputDir}`,
  "--publish",
  "never",
]

console.log(`Building desktop release in ${tempOutputDir}`)
const result = spawnSync(process.execPath, [electronBuilderCli(), ...args], {
  cwd: projectDir,
  env: {
    ...process.env,
    CSC_IDENTITY_AUTO_DISCOVERY: "false",
  },
  stdio: "inherit",
})

if (result.error) {
  throw result.error
}

if (result.status !== 0) {
  process.exit(result.status ?? 1)
}

resetReleaseDir()
copyReleaseArtifacts(tempOutputDir)

try {
  fs.rmSync(tempBaseDir, { recursive: true, force: true })
} catch (error) {
  console.warn(`Could not remove temporary build folder ${tempBaseDir}: ${error.message}`)
}

console.log(`Desktop release artifacts copied to ${releaseDir}`)

import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import { fileURLToPath } from "node:url"
import test from "node:test"

const runner = fileURLToPath(new URL("./test-timezones.mjs", import.meta.url))
const zones = ["UTC", "Asia/Kolkata", "America/New_York", "Pacific/Kiritimati", "America/Sao_Paulo", "Pacific/Apia", "Australia/Lord_Howe"]

function runWithStub(outcome) {
  const preload = `
    import childProcess from "node:child_process"
    import { syncBuiltinESMExports } from "node:module"
    let calls = 0
    childProcess.spawnSync = (command, args, options) => {
      calls++
      console.log("CALL " + JSON.stringify({ command, args, cwd: options.cwd, timezone: options.env.TZ }))
      ${outcome}
    }
    syncBuiltinESMExports()
  `
  return spawnSync(process.execPath, ["--import", `data:text/javascript,${encodeURIComponent(preload)}`, runner], {
    encoding: "utf8",
    env: { ...process.env, TZ: "Europe/London" },
  })
}

function invocations(result) {
  return result.stdout.split("\n").filter(line => line.startsWith("CALL ")).map(line => JSON.parse(line.slice(5)))
}

test("runs the full calendar suite in all seven zones with bounded workers", () => {
  const result = runWithStub("return { status: 0 }")
  assert.equal(result.status, 0, result.stderr)
  const calls = invocations(result)
  assert.deepEqual(calls.map(call => call.timezone), zones)
  for (const call of calls) {
    assert.equal(call.command, process.execPath)
    assert.equal(call.cwd, fileURLToPath(new URL("../", import.meta.url)))
    assert.deepEqual(call.args.slice(1, 3), ["run", "--maxWorkers=4"])
    for (const suite of [
      "src/lib/calendar-range.test.ts",
      "src/lib/calendar-projection.test.ts",
      "src/lib/calendar-time-grid.test.ts",
      "src/lib/calendar-time-edit.test.ts",
      "src/components/calendar/month.test.tsx",
      "src/components/calendar/time-grid.test.tsx",
      "src/components/calendar/year.test.tsx",
      "src/components/calendar-modes.test.tsx",
    ]) assert.ok(call.args.includes(suite), `Missing ${suite}`)
  }
})

test("propagates a failing zone's exit code and stops before later zones", () => {
  const result = runWithStub("return { status: calls === 3 ? 7 : 0 }")
  assert.equal(result.status, 7, result.stderr)
  assert.deepEqual(invocations(result).map(call => call.timezone), zones.slice(0, 3))
})

test("signal termination fails instead of reporting success", () => {
  const result = runWithStub('return { status: null, signal: "SIGTERM" }')
  assert.equal(result.status, 1, result.stderr)
  assert.equal(invocations(result).length, 1)
})

test("failure to start Vitest fails instead of reporting success", () => {
  const result = runWithStub('return { status: null, error: new Error("Synthetic spawn failure") }')
  assert.notEqual(result.status, 0)
  assert.match(result.stderr, /Synthetic spawn failure/)
  assert.equal(invocations(result).length, 1)
})

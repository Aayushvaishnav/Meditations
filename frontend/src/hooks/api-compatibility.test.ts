import { describe, expect, it } from "vitest"
import * as publicApi from "./api"
import * as tasks from "./tasks"
import * as journal from "./journal"
import * as ai from "./ai"
import * as calendarImports from "./calendar-imports"
import { tasksKey } from "./task-cache"

// Both entry points must use the same implementations, not parallel cache owners.
describe("domain hook public compatibility", () => {
  it.each([
    ["tasks", tasks], ["journal", journal], ["AI", ai], ["calendar imports", calendarImports],
  ] as const)("preserves all %s exports through api.ts", (_name, domain) => {
    for (const [name, value] of Object.entries(domain)) {
      expect(publicApi).toHaveProperty(name, value)
    }
  })

  it("retains the canonical task query key by identity", () => {
    expect(publicApi.qk.tasks).toBe(tasksKey)
    expect(publicApi.qk.tasks).toEqual(["tasks"])
  })
})

import { describe, expect, it } from "vitest"
import { indexProgress, localSaveProgress, reviewProgress } from "./progress-state"

describe("independent progress receipts", () => {
  it("distinguishes queued, in-flight and confirmed local writes", () => {
    expect(localSaveProgress("queued").kind).toBe("pending")
    expect(localSaveProgress("saving").kind).toBe("pending")
    expect(localSaveProgress("saved").kind).toBe("ready")
    expect(localSaveProgress("failed").kind).toBe("error")
    expect(localSaveProgress("removed").label).toContain("cleared")
  })
  it("never treats a stream preview or unavailable index as completed", () => {
    expect(reviewProgress("reviewing").kind).toBe("pending")
    expect(reviewProgress("failed").kind).toBe("error")
    expect(reviewProgress("saved").kind).toBe("ready")
    expect(indexProgress("semantic", "missing").kind).toBe("unavailable")
    expect(indexProgress("semantic", "unavailable").kind).toBe("unavailable")
    expect(indexProgress("keyword", "ready").kind).toBe("ready")
    expect(indexProgress("keyword", "not_applicable").kind).toBe("idle")
  })
})

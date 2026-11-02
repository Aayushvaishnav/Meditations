// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest"
import { api, ApiError } from "./client"

const fetchMock = vi.fn<typeof fetch>()

afterEach(() => {
  vi.unstubAllGlobals()
  delete window.__BACKEND_BASE__
  fetchMock.mockReset()
})

describe("file downloads", () => {
  it.each(["/backup", "/export"])("uses the active sidecar URL and reads %s as binary", async (path) => {
    window.__BACKEND_BASE__ = "http://127.0.0.1:43871"
    const bytes = new Uint8Array([83, 81, 76, 105, 116, 101, 0, 255])
    const blob = new Blob([bytes], { type: "application/vnd.sqlite3" })
    const readBlob = vi.fn().mockResolvedValue(blob)
    const readJson = vi.fn()
    fetchMock.mockResolvedValue({ ok: true, blob: readBlob, json: readJson } as unknown as Response)
    vi.stubGlobal("fetch", fetchMock)

    expect(await api.download(path)).toBe(blob)
    expect(fetchMock).toHaveBeenCalledWith(`http://127.0.0.1:43871/api${path}`, expect.objectContaining({ method: "POST" }))
    expect(readBlob).toHaveBeenCalledOnce()
    expect(readJson).not.toHaveBeenCalled()
  })

  it("surfaces server errors instead of downloading an error document", async () => {
    const readBlob = vi.fn()
    fetchMock.mockResolvedValue({
      ok: false, status: 500, text: async () => JSON.stringify({ detail: "Could not create backup" }), blob: readBlob,
    } as unknown as Response)
    vi.stubGlobal("fetch", fetchMock)

    await expect(api.download("/backup")).rejects.toMatchObject({ status: 500, message: "Could not create backup" })
    expect(readBlob).not.toHaveBeenCalled()
  })

  it("reports an unreachable backend", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"))
    vi.stubGlobal("fetch", fetchMock)
    await expect(api.download("/backup")).rejects.toBeInstanceOf(ApiError)
  })

  it("reports an interrupted binary response", async () => {
    fetchMock.mockResolvedValue({ ok: true, blob: async () => { throw new Error("Connection interrupted") } } as unknown as Response)
    vi.stubGlobal("fetch", fetchMock)
    await expect(api.download("/backup")).rejects.toThrow("Connection interrupted")
  })

  it("keeps JSON requests and empty responses working", async () => {
    fetchMock.mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ status: "ok" }) } as Response)
    fetchMock.mockResolvedValueOnce({ ok: true, status: 204 } as Response)
    vi.stubGlobal("fetch", fetchMock)
    await expect(api.get("/health")).resolves.toEqual({ status: "ok" })
    await expect(api.delete("/tasks/task-id")).resolves.toBeUndefined()
  })
})

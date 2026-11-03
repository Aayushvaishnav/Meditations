import { api } from "@/api/client"

export type FileDownloadResult =
  | { kind: "cancelled" }
  | { kind: "saved" }
  | { kind: "download"; blob: Blob; filename: string }

interface FileDownloadOptions {
  endpoint: string
  body?: unknown
  filename: string
  title: string
  fileType: { name: string; extensions: string[] }
  writeError: string
}

export async function createFileDownload(options: FileDownloadOptions): Promise<FileDownloadResult> {
  const fetchFile = () => options.body === undefined
    ? api.download(options.endpoint)
    : api.download(options.endpoint, options.body)
  if ("__TAURI_INTERNALS__" in window) {
    const { save } = await import("@tauri-apps/plugin-dialog")
    const path = await save({
      title: options.title,
      defaultPath: options.filename,
      filters: [options.fileType],
    })
    if (path === null) return { kind: "cancelled" }
    const blob = await fetchFile()
    const { writeFile } = await import("@tauri-apps/plugin-fs")
    try {
      // Exclusive creation preserves existing files, including the live database;
      await writeFile(path, new Uint8Array(await blob.arrayBuffer()), { createNew: true, mode: 0o600 })
    } catch (error) {
      throw new Error(options.writeError, { cause: error })
    }
    return { kind: "saved" }
  }
  return { kind: "download", blob: await fetchFile(), filename: options.filename }
}

export function startBrowserDownload(blob: Blob, filename: string): () => void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  try {
    link.href = url
    link.download = filename
    document.body.append(link)
    link.click()
  } catch (error) {
    URL.revokeObjectURL(url)
    throw error
  } finally {
    link.remove()
  }
  // Browsers expose no completion event; retain the URL until the view leaves or retries;
  return () => URL.revokeObjectURL(url)
}

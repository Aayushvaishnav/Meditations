import { createFileDownload, type FileDownloadResult } from "@/lib/file-download"

export function createDataExport(): Promise<FileDownloadResult> {
  return createFileDownload({
    endpoint: "/export",
    filename: `journal-export-${new Date().toISOString().replace(/[:.]/g, "-")}.zip`,
    title: "Export portable data",
    fileType: { name: "ZIP archive", extensions: ["zip"] },
    writeError: "Could not save the export. Choose a new filename and check folder permissions and free space. A failed write may leave an incomplete file.",
  })
}

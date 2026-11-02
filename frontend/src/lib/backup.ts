import { createFileDownload, type FileDownloadResult } from "@/lib/file-download"

export type BackupResult = FileDownloadResult

export function createBackup(): Promise<BackupResult> {
  return createFileDownload({
    endpoint: "/backup",
    filename: `journal-backup-${new Date().toISOString().replace(/[:.]/g, "-")}.db`,
    title: "Save database backup",
    fileType: { name: "SQLite database", extensions: ["db"] },
    writeError: "Could not save the backup. Choose a new filename and check folder permissions and free space. A failed write may leave an incomplete file.",
  })
}

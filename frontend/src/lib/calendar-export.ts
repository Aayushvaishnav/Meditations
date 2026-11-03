import { createFileDownload, type FileDownloadResult } from "@/lib/file-download"

export function createCalendarExport(blockIds: string[]): Promise<FileDownloadResult> {
  return createFileDownload({
    endpoint: "/calendar/export",
    body: { block_ids: [...blockIds] },
    filename: "meditations-calendar.ics",
    title: "Export work blocks",
    fileType: { name: "iCalendar", extensions: ["ics"] },
    writeError: "Could not save the calendar. Choose a new filename and check folder permissions and free space. A failed write may leave an incomplete file.",
  })
}

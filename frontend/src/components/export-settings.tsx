import { Download, Files, LoaderCircle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useDataExport } from "@/hooks/api"

export function ExportSettings() {
  const exportData = useDataExport()
  return (
    <section className="glass rounded-2xl p-5" aria-labelledby="export-heading">
      <h2 id="export-heading" className="flex items-center gap-2 text-sm font-semibold">
        <Files className="size-4 text-primary" aria-hidden="true" />
        Portable data export
      </h2>
      <div className="mt-4 space-y-3">
        <p className="text-sm text-muted-foreground">
          Take your data outside the app. Save a ZIP with Markdown journals, JSON tasks, focus history, habits and saved reviews, plus a format guide.
        </p>
        <p className="text-sm text-muted-foreground">
          Application settings and provider credentials saved in Settings are excluded. The ZIP is unencrypted and contains private content. Review it before sharing.
        </p>
        <Button variant="outline" className="min-h-11" disabled={exportData.isPending} onClick={() => exportData.mutate()}>
          {exportData.isPending
            ? <LoaderCircle className="motion-safe:animate-spin" aria-hidden="true" />
            : <Download aria-hidden="true" />}
          {exportData.isPending ? "Preparing export…" : "Export data (.zip)"}
        </Button>
        <div role="status" aria-live="polite" className="text-sm text-muted-foreground">
          {exportData.isPending && "Preparing your portable export. Keep this view open."}
          {exportData.isSuccess && exportData.data.kind === "saved" && "Export saved to the selected file."}
          {exportData.isSuccess && exportData.data.kind === "download-started" && "Download started. Check your browser downloads for the .zip file."}
          {exportData.isSuccess && exportData.data.kind === "cancelled" && "Export cancelled. No file was created."}
        </div>
        {exportData.isError && (
          <p role="alert" className="text-sm text-destructive">
            {exportData.error.message} Try exporting again.
          </p>
        )}
        <p className="text-xs text-muted-foreground">
          Includes committed data across all dates and lists. Finish saving edits first. Use Database backup for a restorable copy; ZIP import is unavailable.
        </p>
      </div>
    </section>
  )
}

import { DatabaseBackup, Download, LoaderCircle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useBackup } from "@/hooks/api"

export function BackupSettings() {
  const backup = useBackup()
  return (
    <section className="glass rounded-2xl p-5" aria-labelledby="backup-heading">
      <h2 id="backup-heading" className="flex items-center gap-2 text-sm font-semibold">
        <DatabaseBackup className="size-4 text-primary" aria-hidden="true" />
        Database backup
      </h2>
      <div className="mt-4 space-y-3">
        <p className="text-sm text-muted-foreground">
          Save a snapshot of committed tasks, journals, ratings, reviews, habits, focus history and settings while the app stays open.
        </p>
        <p className="text-sm text-muted-foreground">
          Backups are unencrypted and include saved API keys and private journal content. Store the file securely. Choose a new filename on desktop; existing files are preserved.
        </p>
        <Button variant="outline" className="min-h-11" disabled={backup.isPending} onClick={() => backup.mutate()}>
          {backup.isPending
            ? <LoaderCircle className="motion-safe:animate-spin" aria-hidden="true" />
            : <Download aria-hidden="true" />}
          {backup.isPending ? "Preparing backup…" : "Save backup"}
        </Button>
        <div role="status" aria-live="polite" className="text-sm text-muted-foreground">
          {backup.isPending && "Preparing your database snapshot. Keep this view open."}
          {backup.isSuccess && backup.data.kind === "saved" && "Backup saved to the selected file."}
          {backup.isSuccess && backup.data.kind === "download-started" && "Download started. Check your browser downloads for the .db file."}
          {backup.isSuccess && backup.data.kind === "cancelled" && "Backup cancelled. No file was created."}
        </div>
        {backup.isError && (
          <p role="alert" className="text-sm text-destructive">
            {backup.error.message} Try saving the backup again.
          </p>
        )}
        <p className="text-xs text-muted-foreground">
          Restore requires the offline restore command documented in the project README. Quit the app before restoring.
        </p>
      </div>
    </section>
  )
}

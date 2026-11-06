export type ProgressState = {
  kind: "idle" | "pending" | "ready" | "error" | "unavailable"
  label: string
  detail: string
}

export type LocalSaveState = "unchanged" | "queued" | "saving" | "failed" | "saved" | "removed"

export function localSaveProgress(state: LocalSaveState): ProgressState {
  switch (state) {
    case "unchanged": return { kind: "idle", label: "No unsaved changes", detail: "Search indexing and AI review have separate status below." }
    case "queued": return { kind: "pending", label: "Unsaved changes", detail: "Waiting to save to the local database." }
    case "saving": return { kind: "pending", label: "Saving locally…", detail: "Waiting for the local database to confirm this save." }
    case "failed": return { kind: "error", label: "Local save failed", detail: "Keep this entry open. Retry saves the text and ratings currently in the editor." }
    case "saved": return { kind: "ready", label: "Saved locally", detail: "The local database confirmed the save. This does not mean an AI review or remote sync completed." }
    case "removed": return { kind: "ready", label: "Entry cleared locally", detail: "The local database confirmed removal of the empty entry." }
  }
}

export function reviewProgress(state: "checking" | "unavailable" | "not_reviewed" | "reviewing" | "saved" | "failed"): ProgressState {
  switch (state) {
    case "checking": return { kind: "pending", label: "Checking saved AI review…", detail: "Local journal saving works independently." }
    case "unavailable": return { kind: "unavailable", label: "AI review status unavailable", detail: "Retry loading the day score to check the last saved review." }
    case "not_reviewed": return { kind: "idle", label: "No saved AI review", detail: "Run a review when you want feedback from your configured provider." }
    case "reviewing": return { kind: "pending", label: "AI review in progress", detail: "Streamed feedback is a preview until the backend confirms completion." }
    case "saved": return { kind: "ready", label: "AI review saved", detail: "This is a saved review snapshot; later journal edits are reviewed only when you run it again." }
    case "failed": return { kind: "error", label: "AI review failed", detail: "Your local journal and any previously saved review remain available. Run the review again to retry." }
  }
}

export interface DocumentIndexStatus {
  date: string
  entry_exists: boolean
  updated_at: string | null
  keyword: "ready" | "missing" | "not_applicable"
  semantic: "ready" | "missing" | "unavailable" | "not_applicable"
}

export function indexProgress(kind: "keyword" | "semantic", state: DocumentIndexStatus["semantic"]): ProgressState {
  const name = kind === "keyword" ? "Keyword search" : "Semantic search"
  switch (state) {
    case "ready": return { kind: "ready", label: `${name} ready`, detail: "Indexed for the last persisted version of this entry." }
    case "missing": return { kind: "unavailable", label: `${name} index missing`, detail: "Retry indexing to rebuild search for the last persisted entry. Your locally saved entry is unchanged." }
    case "unavailable": return { kind: "unavailable", label: `${name} unavailable`, detail: "The local vector extension is unavailable. Keyword search works independently." }
    case "not_applicable": return { kind: "idle", label: `${name}: no searchable text`, detail: "Text is indexed for search; mood and energy are saved separately." }
  }
}

import type { Section } from "@/stores/ui"

const SECTION_LABELS: Record<Section, string> = {
  tasks: "tasks",
  journal: "journal",
  insights: "insights",
  second_brain: "Second Brain",
  settings: "settings",
}

export function SectionLoading({ section }: { section: Section }) {
  return (
    <main className="min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto" aria-busy="true">
      <div className="mx-auto max-w-3xl px-6 py-12">
        <p role="status" className="text-sm text-muted-foreground">
          Loading {SECTION_LABELS[section]}…
        </p>
      </div>
    </main>
  )
}

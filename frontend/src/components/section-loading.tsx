import { SectionLayout } from "@/components/section-layout"
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
    <SectionLayout width={section === "settings" ? "reading" : "workspace"} aria-busy="true">
        <p role="status" className="text-sm text-muted-foreground">
          Loading {SECTION_LABELS[section]}…
        </p>
    </SectionLayout>
  )
}

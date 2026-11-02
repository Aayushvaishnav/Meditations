---
version: 1
slug: "frontend-src-components-settings-tsx"
primary_target: "frontend/src/components/settings.tsx"
related_targets: ["frontend/src/components/export-settings.tsx","frontend/src/components/backup-settings.tsx"]
---

## Direction contract

THESIS: Portable export is a separate action from database recovery; make its scope and privacy boundary clear within the existing Settings surface.

OWN-WORLD: Inherit Settings' Geist typography, semantic theme colors, existing glass section treatment, rounded corners, and outline buttons. This is an Operate-mode local extension, not a redesign.

STORY: The user finds backup and export together, understands that ZIP contains readable Markdown and JSON instead of credentials/settings, exports committed data, and receives pending, completion, cancellation, or retry feedback.

FIRST VIEWPORT: Place Portable data export immediately below Database backup, using its existing heading/body/action/status hierarchy and responsive centered column. Keep the export action at least 44px tall. Separate keyboard focus and polite status feedback for both actions.

FORM: A new self-contained Settings section inside the existing surface; no concept seed or replacement visual system. Browser downloads and native save dialogs share behavior while maintaining independent lifetimes. Honor reduced motion for the progress spinner.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance. This local extension preserves the incumbent identity and introduces no shipping raster assets or global DESIGN.md changes.

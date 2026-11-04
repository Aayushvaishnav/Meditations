// @vitest-environment jsdom
import { Editor, Mark } from "@tiptap/core"
import { afterEach, describe, expect, it, vi } from "vitest"
import { journalExtensions, getJournalMarkdown } from "./extensions"

const editors: Editor[] = []
function makeEditor(content = "", extra: Mark[] = []) {
  const editor = new Editor({ extensions: [...journalExtensions(), ...extra], content })
  editors.push(editor)
  return editor
}
afterEach(() => { editors.splice(0).forEach((editor) => editor.destroy()) })

describe("journal Markdown persistence", () => {
  it.each([
    "# Heading one\n\n## Heading two\n\n### Heading three\n\n#### Heading four\n\n##### Heading five\n\n###### Heading six",
    "**Bold** and *italic* and ~~strike~~ and ***~~combined~~***",
    "Inline `const x = 1` and [a link](https://example.com/path?q=1)",
    "```js\nconst x = 1\n```",
    "> A quote\n>\n> Another paragraph",
    "- Parent\n  - Nested\n\n1. First\n2. Second",
    "- [ ] Task\n  - [x] Nested done\n- [x] Done",
    "First line\nSecond line\n\nAnother paragraph",
  ])("retains the document after repeated serialization: %s", (markdown) => {
    const original = makeEditor(markdown)
    const serialized = getJournalMarkdown(original)
    const restored = makeEditor(serialized)
    expect(restored.getJSON()).toEqual(original.getJSON())
    expect(getJournalMarkdown(restored)).toBe(serialized)
    expect(restored.state.doc.textContent).not.toBe("")
  })

  it("retains combined command-applied marks and links after reload", () => {
    const editor = makeEditor("Selected words")
    editor.chain().setTextSelection({ from: 1, to: 15 }).toggleBold().toggleItalic().toggleStrike().setLink({ href: "https://example.com" }).run()
    const restored = makeEditor(getJournalMarkdown(editor))
    restored.commands.setTextSelection({ from: 1, to: 15 })
    for (const mark of ["bold", "italic", "strike", "link"]) expect(restored.isActive(mark)).toBe(true)
    expect(restored.state.doc.textContent).toBe("Selected words")
  })

  it("keeps unsupported underline and highlight out of the production schema", () => {
    const editor = makeEditor()
    expect(editor.schema.marks.underline).toBeUndefined()
    expect(editor.schema.marks.highlight).toBeUndefined()
  })

  it("demonstrates why an HTML-only highlight cannot pass the persistence gate", () => {
    const highlight = Mark.create({ name: "highlight", parseHTML: () => [{ tag: "mark" }], renderHTML: () => ["mark", 0] })
    const editor = makeEditor("Important words", [highlight])
    editor.chain().selectAll().setMark("highlight").run()
    expect(editor.getHTML()).toContain("<mark>")
    const warning = vi.spyOn(console, "warn").mockImplementation(() => {})
    try {
      const serialized = getJournalMarkdown(editor)
      expect(serialized).toBe("Important words")
      expect(makeEditor(serialized, [highlight]).getJSON()).not.toEqual(editor.getJSON())
    } finally { warning.mockRestore() }
  })
})

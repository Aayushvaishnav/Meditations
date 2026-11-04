import StarterKit from "@tiptap/starter-kit"
import { TaskItem, TaskList } from "@tiptap/extension-list"
import { Markdown } from "tiptap-markdown"
import type { Editor } from "@tiptap/core"

// Only expose marks with a Markdown serializer; underline and highlight are lossy.
export function journalExtensions() {
  return [
    StarterKit.configure({ underline: false, link: { openOnClick: false } }),
    TaskList,
    TaskItem.configure({ nested: true }),
    Markdown.configure({ html: false, breaks: true }),
  ]
}

export function getJournalMarkdown(editor: Editor): string {
  return (editor.storage as unknown as { markdown: { getMarkdown(): string } }).markdown.getMarkdown()
}

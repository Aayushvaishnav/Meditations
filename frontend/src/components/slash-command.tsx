import { Extension, type Editor, type Range } from "@tiptap/core"
import { PluginKey } from "@tiptap/pm/state"
import Suggestion, { exitSuggestion } from "@tiptap/suggestion"

import { SlashPopup } from "./journal/slash-menu"

export const slashPluginKey = new PluginKey("slashCommands")

export interface SlashItem {
  label: string
  hint: string
  keywords?: string
  command: (editor: Editor, range: Range) => void
}

export type AssistAction = "improve" | "continue" | "summarize"

function items(onActivity: (editor: Editor) => void, onAI: (editor: Editor, action: AssistAction) => void): SlashItem[] {
  return [
    {
      label: "Heading 1",
      hint: "Big section",
      command: (editor, range) => editor.chain().focus().deleteRange(range).setNode("heading", { level: 1 }).run(),
    },
    {
      label: "Heading 2",
      hint: "Medium section",
      command: (editor, range) => editor.chain().focus().deleteRange(range).setNode("heading", { level: 2 }).run(),
    },
    {
      label: "Heading 3",
      hint: "Small section",
      command: (editor, range) => editor.chain().focus().deleteRange(range).setNode("heading", { level: 3 }).run(),
    },
    {
      label: "Bullet list",
      hint: "Simple list",
      command: (editor, range) => editor.chain().focus().deleteRange(range).toggleBulletList().run(),
    },
    {
      label: "To-do list",
      hint: "Checkable items",
      keywords: "task checkbox",
      command: (editor, range) => editor.chain().focus().deleteRange(range).toggleTaskList().run(),
    },
    {
      label: "Quote",
      hint: "Callout / highlight",
      command: (editor, range) => editor.chain().focus().deleteRange(range).toggleBlockquote().run(),
    },
    {
      label: "Code block",
      hint: "Monospace block",
      command: (editor, range) => editor.chain().focus().deleteRange(range).toggleCodeBlock().run(),
    },
    {
      label: "Divider",
      hint: "Horizontal rule",
      command: (editor, range) => editor.chain().focus().deleteRange(range).setHorizontalRule().run(),
    },
    {
      label: "Day activity",
      hint: "Tasks done, focus time, habits",
      keywords: "embed rollup stats",
      command: (editor) => onActivity(editor),
    },
    {
      label: "AI: Improve entry",
      hint: "Rewrite clearer, keep your voice",
      keywords: "ai rewrite polish",
      command: (editor, range) => {
        editor.chain().focus().deleteRange(range).run()
        onAI(editor, "improve")
      },
    },
    {
      label: "AI: Continue writing",
      hint: "Pick up where you stopped",
      keywords: "ai continue",
      command: (editor, range) => {
        editor.chain().focus().deleteRange(range).run()
        onAI(editor, "continue")
      },
    },
    {
      label: "AI: Summarize entry",
      hint: "Short summary of the whole entry",
      keywords: "ai tldr summary",
      command: (editor, range) => {
        editor.chain().focus().deleteRange(range).run()
        onAI(editor, "summarize")
      },
    },
  ]
}

export const SlashCommands = Extension.create<{
  onActivity: (editor: Editor) => void
  onAI: (editor: Editor, action: AssistAction) => void
}>({
  name: "slashCommands",

  addOptions() {
    return { onActivity: () => {}, onAI: () => {} }
  },

  addProseMirrorPlugins() {
    const onActivity = this.options.onActivity
    const onAI = this.options.onAI
    return [
      Suggestion<SlashItem>({
        editor: this.editor,
        pluginKey: slashPluginKey,
        char: "/",
        startOfLine: false,
        items: ({ query }) =>
          items(onActivity, onAI).filter((item) =>
            (item.label + " " + (item.keywords ?? "")).toLowerCase().includes(query.toLowerCase()),
          ),
        command: ({ editor, range, props }) => props.command(editor, range),
        render: () => {
          let popup: SlashPopup | null = null
          return {
            onStart: (props) => {
              popup = new SlashPopup(props.editor.view.dom, () => exitSuggestion(props.editor.view, slashPluginKey))
              popup.update(props)
            },
            onUpdate: (props) => {
              popup?.update(props)
            },
            onKeyDown: (props) => popup?.onKeyDown(props) ?? false,
            onExit: () => {
              popup?.destroy()
              popup = null
            },
          }
        },
      }),
    ]
  },
})

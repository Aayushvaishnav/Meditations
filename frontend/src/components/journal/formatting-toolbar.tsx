import { useEffect, useState } from "react"
import { useEditorState, type Editor } from "@tiptap/react"
import { isAllowedUri, type LinkOptions } from "@tiptap/extension-link"
import {
  Bold, Italic, Strikethrough, Code, List, ListOrdered, ListTodo, Quote,
  SquareCode, Link, RemoveFormatting, Undo, Redo, type LucideIcon,
} from "lucide-react"
import { Button } from "@/components/ui/button"

const target = "pointer-coarse:min-h-11 pointer-coarse:min-w-11"

type LinkDraft =
  | { status: "closed" }
  | { status: "editing"; from: number; to: number; doc: Editor["state"]["doc"] }

export function FormattingToolbar({ editor, compact = false }: { editor: Editor; compact?: boolean }) {
  const [composing, setComposing] = useState(false)
  const [linkComposing, setLinkComposing] = useState(false)
  const [link, setLink] = useState<LinkDraft>({ status: "closed" })
  const [url, setUrl] = useState("")
  const [error, setError] = useState("")

  useEffect(() => {
    if (editor.isDestroyed) return
    const start = () => setComposing(true)
    const end = () => setComposing(false)
    const dom = editor.view.dom
    dom.addEventListener("compositionstart", start)
    dom.addEventListener("compositionend", end)
    return () => {
      dom.removeEventListener("compositionstart", start)
      dom.removeEventListener("compositionend", end)
    }
  }, [editor])

  const state = useEditorState({
    editor,
    selector: ({ editor: current }) => ({
      editable: current.isEditable,
      doc: current.state.doc,
      selection: current.state.selection,
      active: ["bold", "italic", "strike", "code", "bulletList", "orderedList", "taskList", "blockquote", "codeBlock", "link"].filter(name => current.isActive(name)),
      heading: current.isActive("heading") ? String(current.getAttributes("heading").level) : "paragraph",
      can: current.can(),
    }),
  })
  const disabled = !state.editable || composing || linkComposing
  const staleSelection = link.status === "editing"
    && (link.from !== state.selection.from || link.to !== state.selection.to)
  const stale = link.status === "editing" && (link.doc !== state.doc || staleSelection)

  const action = (label: string, Icon: LucideIcon, run: () => void, can: boolean, active?: string) => (
    <Button
      key={label}
      type="button"
      variant="ghost"
      size="icon"
      className={`${target} ${active && state.active.includes(active) ? "bg-muted text-foreground" : "text-muted-foreground"}`}
      aria-label={label}
      title={label}
      aria-pressed={active ? state.active.includes(active) : undefined}
      disabled={disabled || !can}
      onPointerDown={event => event.preventDefault()}
      onClick={run}
    >
      <Icon aria-hidden="true" />
    </Button>
  )

  const close = () => {
    setLink({ status: "closed" })
    setError("")
  }
  const cancel = () => {
    close()
    if (!disabled) editor.commands.focus()
  }
  const openLink = () => {
    const { from, to } = editor.state.selection
    setLink({ status: "editing", from, to, doc: editor.state.doc })
    setUrl(editor.getAttributes("link").href ?? "")
    setError("")
  }
  const restore = () => {
    if (link.status !== "editing" || stale || disabled) return false
    editor.commands.setTextSelection({ from: link.from, to: link.to })
    return true
  }
  const submit = () => {
    if (disabled) return
    const extension = editor.extensionManager.extensions.find(item => item.name === "link")
    const options = extension?.options as LinkOptions | undefined
    const href = url.trim()
    if (!options || !href || !isAllowedUri(href, options.protocols) || !options.isAllowedUri(href, {
      defaultValidate: value => !!isAllowedUri(value, options.protocols),
      protocols: options.protocols,
      defaultProtocol: options.defaultProtocol,
    })) {
      setError("Enter a valid, safe link address.")
      return
    }
    if (restore()) {
      editor.chain().focus().extendMarkRange("link").setLink({ href }).run()
      close()
    }
  }
  const removeLink = () => {
    if (restore()) {
      editor.chain().focus().extendMarkRange("link").unsetLink().run()
      close()
    }
  }

  return (
    <div
      role="group"
      aria-label={compact ? "Selection formatting" : "Journal formatting"}
      className={`flex flex-wrap items-center gap-0.5 text-sm ${compact ? "" : "mb-4 border-b border-border pb-3"}`}
    >
      {!compact && (
        <select
          aria-label="Block style"
          value={state.heading}
          disabled={disabled}
          className={`h-8 max-w-36 rounded-md border border-input bg-background px-2 text-sm ${target}`}
          onChange={event => {
            if (event.target.value === "paragraph") editor.chain().focus().setParagraph().run()
            else editor.chain().focus().setHeading({ level: Number(event.target.value) as 1 | 2 | 3 | 4 | 5 | 6 }).run()
          }}
        >
          <option value="paragraph">Paragraph</option>
          {[1, 2, 3, 4, 5, 6].map(level => <option key={level} value={level}>Heading {level}</option>)}
        </select>
      )}
      {action("Bold", Bold, () => { editor.chain().focus().toggleBold().run() }, state.can.toggleBold(), "bold")}
      {action("Italic", Italic, () => { editor.chain().focus().toggleItalic().run() }, state.can.toggleItalic(), "italic")}
      {action("Strikethrough", Strikethrough, () => { editor.chain().focus().toggleStrike().run() }, state.can.toggleStrike(), "strike")}
      {action("Inline code", Code, () => { editor.chain().focus().toggleCode().run() }, state.can.toggleCode(), "code")}
      {!compact && (
        <>
          {action("Bullet list", List, () => { editor.chain().focus().toggleBulletList().run() }, state.can.toggleBulletList(), "bulletList")}
          {action("Ordered list", ListOrdered, () => { editor.chain().focus().toggleOrderedList().run() }, state.can.toggleOrderedList(), "orderedList")}
          {action("Task list", ListTodo, () => { editor.chain().focus().toggleTaskList().run() }, !!state.can.toggleTaskList?.(), "taskList")}
          {action("Blockquote", Quote, () => { editor.chain().focus().toggleBlockquote().run() }, state.can.toggleBlockquote(), "blockquote")}
          {action("Code block", SquareCode, () => { editor.chain().focus().toggleCodeBlock().run() }, state.can.toggleCodeBlock(), "codeBlock")}
        </>
      )}
      {action("Edit link", Link, openLink, !!state.can.setLink?.({ href: "https://example.com" }), "link")}
      {action("Clear formatting", RemoveFormatting, () => { editor.chain().focus().unsetAllMarks().run() }, !state.selection.empty && state.can.unsetAllMarks())}
      {!compact && (
        <>
          {action("Undo", Undo, () => { editor.chain().focus().undo().run() }, state.can.undo())}
          {action("Redo", Redo, () => { editor.chain().focus().redo().run() }, state.can.redo())}
        </>
      )}
      {link.status === "editing" && (
        <form
          aria-label="Link editor"
          className="flex w-full flex-wrap items-center gap-2 py-1"
          onSubmit={event => {
            event.preventDefault()
            if (!linkComposing) submit()
          }}
          onKeyDown={event => {
            if (event.key !== "Enter" && event.key !== "Escape") return
            if (linkComposing || event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229) {
              event.preventDefault()
              return
            }
            if (event.key === "Escape") {
              event.preventDefault()
              cancel()
            }
          }}
        >
          <input
            autoFocus
            aria-label="Link address"
            value={url}
            disabled={!state.editable || composing || stale}
            onCompositionStart={() => setLinkComposing(true)}
            onCompositionEnd={() => setLinkComposing(false)}
            onChange={event => {
              setUrl(event.target.value)
              setError("")
            }}
            className={`h-8 min-w-0 flex-1 rounded-md border border-input bg-background px-2 ${target}`}
          />
          <Button type="submit" variant="secondary" className={target} disabled={disabled || stale}>
            Apply link
          </Button>
          <Button
            type="button"
            variant="ghost"
            className={target}
            disabled={disabled || stale}
            onPointerDown={event => event.preventDefault()}
            onClick={removeLink}
          >
            Remove link
          </Button>
          <Button
            type="button"
            variant="ghost"
            className={target}
            disabled={composing || linkComposing}
            onPointerDown={event => event.preventDefault()}
            onClick={cancel}
          >
            Cancel
          </Button>
          {(stale || error) && (
            <p role="alert" className="w-full text-destructive">
              {stale ? "The journal or selection changed. Cancel and select the text again." : error}
            </p>
          )}
        </form>
      )}
    </div>
  )
}

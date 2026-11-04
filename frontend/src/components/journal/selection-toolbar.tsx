import { useEffect, useRef } from "react"
import { BubbleMenu } from "@tiptap/react/menus"
import { isTextSelection, posToDOMRect, type Editor } from "@tiptap/core"
import type { Selection } from "@tiptap/pm/state"
import { FormattingToolbar } from "./formatting-toolbar"
import { slashPluginKey } from "@/components/slash-command"

const menuKey = "journalSelectionFormatting"

export function SelectionToolbar({ editor }: { editor: Editor }) {
  const menu = useRef<HTMLDivElement>(null)
  const dismissed = useRef<Selection | undefined>(undefined)

  useEffect(() => {
    if (editor.isDestroyed) return
    const dom = editor.view.dom
    const update = () => {
      if (!editor.isDestroyed) editor.view.dispatch(editor.state.tr.setMeta(menuKey, "updatePosition"))
    }
    const hide = () => {
      if (!editor.isDestroyed) editor.view.dispatch(editor.state.tr.setMeta(menuKey, "hide"))
    }
    const focusOutside = (event: FocusEvent) => {
      if (event.target instanceof Node && !dom.contains(event.target) && !menu.current?.contains(event.target)) hide()
    }
    const escape = (event: KeyboardEvent) => {
      const fromEditor = event.target instanceof Node && dom.contains(event.target)
      // ProseMirror consumes native Escape; link forms may consume it for IME or cancellation.
      if (event.key !== "Escape" || (event.defaultPrevented && !fromEditor) || event.isComposing || event.keyCode === 229
        || !menu.current?.isConnected || menu.current.style.visibility === "hidden") return
      dismissed.current = editor.state.selection
      hide()
      if (menu.current.contains(document.activeElement)) editor.commands.focus()
      event.preventDefault()
    }
    const resetDismissal = () => {
      if (dismissed.current && !dismissed.current.eq(editor.state.selection)) dismissed.current = undefined
    }
    editor.on("selectionUpdate", resetDismissal)
    const observer = typeof ResizeObserver === "undefined" ? undefined : new ResizeObserver(update)
    if (menu.current) observer?.observe(menu.current)
    for (let node: HTMLElement | null = dom; node; node = node.parentElement) observer?.observe(node)
    document.addEventListener("scroll", update, true)
    document.addEventListener("keydown", escape)
    document.addEventListener("focusin", focusOutside)
    dom.addEventListener("compositionstart", hide)
    window.visualViewport?.addEventListener("resize", update)
    window.visualViewport?.addEventListener("scroll", update)
    return () => {
      observer?.disconnect()
      editor.off("selectionUpdate", resetDismissal)
      document.removeEventListener("scroll", update, true)
      document.removeEventListener("keydown", escape)
      document.removeEventListener("focusin", focusOutside)
      dom.removeEventListener("compositionstart", hide)
      window.visualViewport?.removeEventListener("resize", update)
      window.visualViewport?.removeEventListener("scroll", update)
    }
  }, [editor])

  return (
    <BubbleMenu
      ref={menu}
      editor={editor}
      pluginKey={menuKey}
      appendTo={() => document.body}
      updateDelay={0}
      resizeDelay={0}
      className="journal-selection-toolbar rounded-xl bg-popover p-1 text-popover-foreground shadow-lg ring-1 ring-border"
      getReferencedVirtualElement={() => ({
        contextElement: editor.view.dom,
        getBoundingClientRect: () => posToDOMRect(editor.view, editor.state.selection.from, editor.state.selection.to),
      })}
      shouldShow={({ state, view, element }) => {
        const selection = state.selection
        return editor.isEditable && !view.composing && isTextSelection(selection) && !selection.empty
          && !!state.doc.textBetween(selection.from, selection.to).trim()
          && !dismissed.current?.eq(selection)
          && !slashPluginKey.getState(state)?.active
          && (view.hasFocus() || element.contains(document.activeElement))
      }}
      options={{ strategy: "fixed", placement: "top", offset: 8, flip: { padding: 12 }, shift: { padding: 12 }, hide: true }}
    >
      <FormattingToolbar editor={editor} compact />
    </BubbleMenu>
  )
}

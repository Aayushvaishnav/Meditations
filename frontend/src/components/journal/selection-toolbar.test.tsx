// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { Editor } from "@tiptap/core"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { journalExtensions } from "./extensions"
import { SelectionToolbar } from "./selection-toolbar"

let editor: Editor
beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue(new DOMRect(0, 0, 1024, 768))
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(1024)
  vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(768)
  editor = new Editor({ extensions: journalExtensions(), content: "Some selected words" })
  document.body.appendChild(editor.view.dom)
  vi.spyOn(editor.view, "coordsAtPos").mockReturnValue({ left: 80, right: 180, top: 180, bottom: 200 })
})
afterEach(async () => {
  cleanup()
  editor.destroy()
  await new Promise(resolve => requestAnimationFrame(resolve))
  document.body.innerHTML = ""
  vi.restoreAllMocks()
})
function select(from = 1, to = 5) {
  act(() => {
    editor.view.dom.focus()
    editor.commands.setTextSelection({ from, to })
  })
}
async function menu() {
  return await screen.findByRole("group", { name: "Selection formatting" })
}

it("dismisses with Escape only until the selection moves, even returning to the original range", async () => {
  render(<SelectionToolbar editor={editor} />)
  select()
  await menu()
  fireEvent.keyDown(editor.view.dom, { key: "Escape", keyCode: 27 })
  expect(screen.queryByRole("group", { name: "Selection formatting" })).toBeNull()
  select(6, 14)
  await menu()
  select()
  await menu()
  expect(editor.getText()).toBe("Some selected words")
})

it("keeps selection actions usable while the link input has focus", async () => {
  render(<SelectionToolbar editor={editor} />)
  select()
  await menu()
  fireEvent.click(screen.getByRole("button", { name: "Edit link" }))
  const input = screen.getByRole("textbox", { name: "Link address" })
  expect(document.activeElement).toBe(input)
  fireEvent.change(input, { target: { value: "https://example.com" } })
  fireEvent.click(screen.getByRole("button", { name: "Apply link" }))
  expect(editor.getHTML()).toContain('>Some</a> selected words')
})

it("hides during composition and on an empty selection", async () => {
  render(<SelectionToolbar editor={editor} />)
  select()
  await menu()
  fireEvent.compositionStart(editor.view.dom)
  expect(screen.queryByRole("group", { name: "Selection formatting" })).toBeNull()
  fireEvent.compositionEnd(editor.view.dom)
  select(6, 14)
  await menu()
  select(5, 5)
  await waitFor(() => expect(screen.queryByRole("group", { name: "Selection formatting" })).toBeNull())
})

it("removes the portal and listeners when its editor context unmounts", async () => {
  const view = render(<SelectionToolbar editor={editor} />)
  select()
  await menu()
  view.unmount()
  await waitFor(() => expect(document.querySelector(".journal-selection-toolbar")).toBeNull())
  select(6, 14)
  fireEvent.scroll(document)
  expect(screen.queryByRole("group", { name: "Selection formatting" })).toBeNull()
})

it("dismisses when focus leaves both the editor and the floating controls", async () => {
  render(<><SelectionToolbar editor={editor} /><button>Outside action</button></>)
  select()
  await menu()
  act(() => screen.getByRole("button", { name: "Outside action" }).focus())
  expect(screen.queryByRole("group", { name: "Selection formatting" })).toBeNull()
})


it("keeps a composing link input open when Escape is consumed by its form", async () => {
  render(<SelectionToolbar editor={editor} />)
  select()
  await menu()
  fireEvent.click(screen.getByRole("button", { name: "Edit link" }))
  const input = screen.getByRole("textbox", { name: "Link address" })
  fireEvent.compositionStart(input)
  fireEvent.keyDown(input, { key: "Escape" })
  expect(screen.getByRole("textbox", { name: "Link address" })).toBe(input)
  expect(input.hasAttribute("disabled")).toBe(false)
  fireEvent.compositionEnd(input)
})

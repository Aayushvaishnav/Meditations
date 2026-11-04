// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react"
import { DOMParser as ProseMirrorDOMParser } from "@tiptap/pm/model"
import { Editor } from "@tiptap/react"
import { afterEach, expect, it } from "vitest"
import { journalExtensions } from "./extensions"
import { FormattingToolbar } from "./formatting-toolbar"

let editor: Editor
function mount(content = "<p>hello world</p>", compact = false) {
  editor = new Editor({ extensions: journalExtensions() })
  const dom = document.createElement("div")
  dom.innerHTML = content
  editor.commands.setContent(ProseMirrorDOMParser.fromSchema(editor.schema).parse(dom).toJSON())
  document.body.appendChild(editor.view.dom)
  editor.commands.setTextSelection({ from: 1, to: 6 })
  return render(<FormattingToolbar editor={editor} compact={compact} />)
}
function click(name: string) { fireEvent.click(screen.getByRole("button", { name })) }
afterEach(() => { cleanup(); editor?.destroy(); document.body.innerHTML = "" })

it("applies reactive marks and preserves pointer selection", () => {
  mount()
  fireEvent.pointerDown(screen.getByRole("button", { name: "Bold" }))
  click("Bold")
  expect(editor.getHTML()).toContain("<strong>hello</strong>")
  expect(screen.getByRole("button", { name: "Bold" }).getAttribute("aria-pressed")).toBe("true")
  click("Italic")
  expect(editor.isActive("italic")).toBe(true)
  click("Strikethrough")
  expect(editor.isActive("strike")).toBe(true)
})
it("clears only selection marks and preserves heading structure", () => {
  mount("<h2><strong>hello world</strong></h2>")
  click("Clear formatting")
  expect(editor.getHTML()).toContain("<h2>hello<strong> world</strong></h2>")
})
it("supports block styles, lists, history and compact composition", () => {
  const view = mount()
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "3" } })
  expect(editor.isActive("heading", { level: 3 })).toBe(true)
  click("Undo")
  expect(editor.isActive("paragraph")).toBe(true)
  click("Redo")
  expect(editor.isActive("heading", { level: 3 })).toBe(true)
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "paragraph" } })
  click("Task list")
  expect(editor.isActive("taskList")).toBe(true)
  view.rerender(<FormattingToolbar editor={editor} compact />)
  expect(screen.queryByRole("combobox")).toBeNull()
  expect(screen.queryByRole("button", { name: "Undo" })).toBeNull()
  expect(screen.getByRole("button", { name: "Bold" })).toBeTruthy()
})
it("validates links, preserves selection through input focus, cancels and removes", () => {
  mount()
  click("Edit link")
  const input = screen.getByRole("textbox", { name: "Link address" })
  fireEvent.focus(input)
  fireEvent.change(input, { target: { value: "javascript:alert(1)" } })
  click("Apply link")
  expect(screen.getByRole("alert")).toBeTruthy()
  expect(editor.getHTML()).not.toContain("<a")
  fireEvent.change(input, { target: { value: "https://example.com" } })
  click("Apply link")
  expect(editor.getHTML()).toContain('href="https://example.com"')
  expect(editor.getHTML()).toContain('>hello</a> world')
  click("Edit link")
  click("Cancel")
  expect(editor.getHTML()).toContain("<a")
  click("Edit link")
  click("Remove link")
  expect(editor.getHTML()).toBe("<p>hello world</p>")
})
it("rejects stale link selections after document changes", () => {
  mount()
  click("Edit link")
  act(() => { editor.commands.insertContent("changed") })
  expect(screen.getByRole("alert")).toBeTruthy()
  expect((screen.getByRole("button", { name: "Apply link" }) as HTMLButtonElement).disabled).toBe(true)
})
it("disables editing for composition and noneditable editors", () => {
  mount()
  fireEvent.compositionStart(editor.view.dom)
  expect((screen.getByRole("button", { name: "Bold" }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.compositionEnd(editor.view.dom)
  expect((screen.getByRole("button", { name: "Bold" }) as HTMLButtonElement).disabled).toBe(false)
  act(() => { editor.setEditable(false) })
  expect((screen.getByRole("button", { name: "Bold" }) as HTMLButtonElement).disabled).toBe(true)
})

it.each([
  ["Bullet list", "bulletList"],
  ["Ordered list", "orderedList"],
  ["Blockquote", "blockquote"],
  ["Code block", "codeBlock"],
  ["Inline code", "code"],
])("toggles %s with real commands", (label, node) => {
  mount()
  click(label)
  expect(editor.isActive(node)).toBe(true)
  click(label)
  expect(editor.isActive(node)).toBe(false)
})

it("keeps clear formatting unavailable for an empty selection", () => {
  mount()
  act(() => { editor.commands.setTextSelection(3) })
  expect((screen.getByRole("button", { name: "Clear formatting" }) as HTMLButtonElement).disabled).toBe(true)
})

it("locks commands but not the address input during link composition", () => {
  mount()
  click("Edit link")
  const input = screen.getByRole("textbox", { name: "Link address" }) as HTMLInputElement
  fireEvent.change(input, { target: { value: "https://example.com" } })
  fireEvent.compositionStart(input)
  expect(input.disabled).toBe(false)
  expect((screen.getByRole("combobox") as HTMLSelectElement).disabled).toBe(true)
  for (const button of screen.getAllByRole("button")) {
    expect((button as HTMLButtonElement).disabled).toBe(true)
  }
  fireEvent.submit(screen.getByRole("form", { name: "Link editor" }))
  fireEvent.keyDown(input, { key: "Enter" })
  fireEvent.keyDown(input, { key: "Escape" })
  expect(screen.getByRole("textbox", { name: "Link address" })).toBe(input)
  expect(editor.getHTML()).toBe("<p>hello world</p>")
  fireEvent.compositionEnd(input)
  expect((screen.getByRole("button", { name: "Cancel" }) as HTMLButtonElement).disabled).toBe(false)
  fireEvent.submit(screen.getByRole("form", { name: "Link editor" }))
  expect(editor.getHTML()).toContain('href="https://example.com"')
  expect(screen.queryByRole("form", { name: "Link editor" })).toBeNull()
})

it.each([{ isComposing: true }, { keyCode: 229 }])(
  "guards native composition keys without composition state: %j",
  nativeEvent => {
    mount()
    click("Edit link")
    const input = screen.getByRole("textbox", { name: "Link address" })
    for (const key of ["Enter", "Escape"]) {
      expect(fireEvent.keyDown(input, { key, ...nativeEvent })).toBe(false)
      expect(screen.getByRole("textbox", { name: "Link address" })).toBe(input)
      expect(editor.getHTML()).toBe("<p>hello world</p>")
    }
    fireEvent.keyDown(input, { key: "Escape" })
    expect(screen.queryByRole("form", { name: "Link editor" })).toBeNull()
  },
)

it("preserves the editor composition lock while a link draft is open", () => {
  mount()
  click("Edit link")
  fireEvent.compositionStart(editor.view.dom)
  expect((screen.getByRole("textbox", { name: "Link address" }) as HTMLInputElement).disabled).toBe(true)
  expect((screen.getByRole("button", { name: "Cancel" }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.compositionEnd(editor.view.dom)
  expect((screen.getByRole("textbox", { name: "Link address" }) as HTMLInputElement).disabled).toBe(false)
  click("Cancel")
  expect(screen.queryByRole("form", { name: "Link editor" })).toBeNull()
})


it("rejects a link draft when a different editor range is selected without changing text", () => {
  mount()
  click("Edit link")
  act(() => { editor.commands.setTextSelection({ from: 7, to: 12 }) })
  expect((screen.getByRole("button", { name: "Apply link" }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.submit(screen.getByRole("form", { name: "Link editor" }))
  expect(editor.getHTML()).toBe("<p>hello world</p>")
})


it("clears marks across paragraphs and nested lists without flattening structure", () => {
  mount("<h2><strong>Heading</strong></h2><p><em>Paragraph</em></p><ul><li><p><s>Parent</s></p><ul><li><p><strong>Nested</strong></p></li></ul></li></ul>")
  const structure: string[] = []
  editor.state.doc.descendants(node => { if (!node.isText) structure.push(node.type.name) })
  const text = editor.getText()
  act(() => { editor.commands.selectAll() })
  click("Clear formatting")
  const clearedStructure: string[] = []
  editor.state.doc.descendants(node => {
    if (!node.isText) clearedStructure.push(node.type.name)
    expect(node.marks).toHaveLength(0)
  })
  expect(clearedStructure).toEqual(structure)
  expect(editor.getText()).toBe(text)
})

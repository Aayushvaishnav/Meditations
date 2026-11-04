// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, getAllByRole } from "@testing-library/dom"
import type { SuggestionKeyDownProps, SuggestionProps } from "@tiptap/suggestion"
import { SlashPopup } from "./journal/slash-menu"
import type { SlashItem } from "./slash-command"

let popup: SlashPopup
let editor: HTMLDivElement
let anchor: DOMRect | null
let props: SuggestionProps<SlashItem>
let resize: ResizeObserverCallback
const dismiss = vi.fn()
const command = vi.fn()
const disconnect = vi.fn()
const viewport = new EventTarget()
function key(value: string, isComposing = false) {
  return popup.onKeyDown({ event: new KeyboardEvent("keydown", { key: value, isComposing }) } as SuggestionKeyDownProps)
}
function options() { return getAllByRole(popup.el, "option") }

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", class {
    constructor(callback: ResizeObserverCallback) { resize = callback }
    observe = vi.fn()
    disconnect = disconnect
  })
  vi.stubGlobal("visualViewport", viewport)
  editor = document.createElement("div")
  document.body.appendChild(editor)
  anchor = new DOMRect(100, 100, 1, 20)
  props = {
    items: Array.from({ length: 12 }, (_, i) => ({ label: `Command ${i}`, hint: `Hint ${i}`, command: vi.fn() })),
    query: "", clientRect: () => anchor, command,
  } as unknown as SuggestionProps<SlashItem>
  popup = new SlashPopup(editor, dismiss)
  popup.update(props)
})
afterEach(() => {
  popup.destroy()
  editor.remove()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

describe("slash command popup", () => {
  it("executes the hovered result once with Enter without moving focus", () => {
    editor.tabIndex = 0
    editor.focus()
    fireEvent.pointerMove(options()[3])
    expect(options()[3].getAttribute("aria-selected")).toBe("true")
    expect(editor.getAttribute("aria-activedescendant")).toBe(options()[3].id)
    expect(document.activeElement).toBe(editor)
    key("Enter")
    key("Enter")
    expect(command).toHaveBeenCalledExactlyOnceWith(props.items[3])
    expect(dismiss).toHaveBeenCalledOnce()
    expect(popup.el.isConnected).toBe(false)
  })

  it("continues keyboard navigation from the hovered result", () => {
    fireEvent.pointerMove(options()[3])
    key("ArrowDown")
    key("Enter")
    expect(command).toHaveBeenCalledExactlyOnceWith(props.items[4])
  })

  it("uses click activation once for mouse, touch and assistive technology", () => {
    const row = options()[2]
    fireEvent.pointerDown(row, { pointerType: "touch" })
    fireEvent.click(row)
    fireEvent.click(row)
    expect(command).toHaveBeenCalledExactlyOnceWith(props.items[2])
  })

  it("preserves rows and scroll position while moving the keyboard selection", () => {
    const rows = options()
    Object.defineProperty(popup.el, "clientHeight", { value: 100 })
    rows.forEach((row, i) => {
      Object.defineProperties(row, { offsetTop: { value: i * 30 }, offsetHeight: { value: 30 } })
    })
    popup.el.scrollTop = 100
    for (let i = 0; i < 5; i++) key("ArrowDown")
    expect(options()[5]).toBe(rows[5])
    expect(popup.el.scrollTop).toBe(80)
    key("ArrowUp")
    expect(popup.el.scrollTop).toBe(80)
  })

  it("wraps in both directions and resets selection when the query changes", () => {
    key("ArrowUp")
    expect(options()[11].getAttribute("aria-selected")).toBe("true")
    key("ArrowDown")
    expect(options()[0].getAttribute("aria-selected")).toBe("true")
    popup.update({ ...props, query: "one", items: [props.items[1]] })
    key("Enter")
    expect(command).toHaveBeenCalledExactlyOnceWith(props.items[1])
  })

  it("handles no matches and ignores composing keyboard events", () => {
    expect(key("Enter", true)).toBe(false)
    popup.update({ ...props, items: [] })
    key("ArrowUp")
    key("Enter")
    expect(command).not.toHaveBeenCalled()
    expect(editor.hasAttribute("aria-activedescendant")).toBe(false)
  })

  it("dismisses Escape without executing a command", () => {
    key("Escape")
    expect(dismiss).toHaveBeenCalledOnce()
    expect(command).not.toHaveBeenCalled()
  })

  it("repositions on nested scrolling, resize and observed layout changes", () => {
    expect(popup.el.style.top).toBe("126px")
    anchor = new DOMRect(110, 150, 1, 20)
    editor.dispatchEvent(new Event("scroll"))
    expect(popup.el.style.top).toBe("176px")
    anchor = new DOMRect(120, 200, 1, 20)
    window.dispatchEvent(new Event("resize"))
    expect(popup.el.style.top).toBe("226px")
    anchor = new DOMRect(130, 250, 1, 20)
    resize([], {} as ResizeObserver)
    expect(popup.el.style.top).toBe("276px")
  })

  it("ignores scrolling within the menu", () => {
    anchor = new DOMRect(100, 200, 1, 20)
    popup.el.dispatchEvent(new Event("scroll"))
    expect(popup.el.style.top).toBe("126px")
  })

  it("clamps edges, flips upwards and bounds the available height", () => {
    Object.defineProperties(popup.el, { offsetHeight: { get: () => 100 }, offsetWidth: { get: () => 220 } })
    anchor = new DOMRect(-5, 700, 10, 20)
    window.dispatchEvent(new Event("resize"))
    expect(popup.el.style.left).toBe("12px")
    expect(popup.el.style.top).toBe("594px")
    anchor = new DOMRect(window.innerWidth - 1, 1, 1, 20)
    window.dispatchEvent(new Event("resize"))
    expect(popup.el.style.left).toBe(`${window.innerWidth - 232}px`)
    expect(Number.parseFloat(popup.el.style.maxHeight)).toBeLessThanOrEqual(280)
  })

  it("hides missing or offscreen anchors and restores them on reentry", () => {
    anchor = null
    window.dispatchEvent(new Event("resize"))
    expect(popup.el.hidden).toBe(true)
    expect(key("Enter")).toBe(false)
    anchor = new DOMRect(10, -30, 1, 20)
    window.dispatchEvent(new Event("resize"))
    expect(popup.el.hidden).toBe(true)
    anchor = new DOMRect(10, 100, 1, 20)
    window.dispatchEvent(new Event("resize"))
    expect(popup.el.hidden).toBe(false)
  })

  it("restores editor attributes and releases listeners and observers on destroy", () => {
    const remove = vi.spyOn(document, "removeEventListener")
    const removeWindow = vi.spyOn(window, "removeEventListener")
    const removeViewport = vi.spyOn(viewport, "removeEventListener")
    popup.destroy()
    expect(popup.el.isConnected).toBe(false)
    expect(editor.hasAttribute("aria-controls")).toBe(false)
    expect(editor.hasAttribute("aria-activedescendant")).toBe(false)
    expect(remove).toHaveBeenCalledWith("scroll", expect.any(Function), true)
    expect(removeWindow).toHaveBeenCalledWith("resize", expect.any(Function))
    expect(removeViewport).toHaveBeenCalledWith("resize", expect.any(Function))
    expect(removeViewport).toHaveBeenCalledWith("scroll", expect.any(Function))
    expect(disconnect).toHaveBeenCalledOnce()
    expect(key("Enter")).toBe(false)
  })
})

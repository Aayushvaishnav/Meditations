import type { SuggestionKeyDownProps, SuggestionProps } from "@tiptap/suggestion"
import type { SlashItem } from "../slash-command"

let nextId = 0
const editorAttributes = ["aria-controls", "aria-activedescendant", "aria-expanded", "aria-haspopup"] as const

export class SlashPopup {
  readonly el = document.createElement("div")
  private state: { kind: "closed" } | { kind: "open"; props: SuggestionProps<SlashItem> } = { kind: "closed" }
  private selectedIndex = 0
  private rows: HTMLButtonElement[] = []
  private observer: ResizeObserver | undefined
  private ancestors: HTMLElement[] = []
  private previousAttributes: Map<string, string | null>

  private editor: HTMLElement
  private dismiss: () => void

  constructor(editor: HTMLElement, dismiss: () => void) {
    this.editor = editor
    this.dismiss = dismiss
    this.previousAttributes = new Map(editorAttributes.map((name) => [name, editor.getAttribute(name)]))
    this.el.id = `slash-menu-${++nextId}`
    this.el.className = "slash-menu"
    this.el.setAttribute("role", "listbox")
    this.el.setAttribute("aria-label", "Journal commands")
    this.el.hidden = true
    document.body.appendChild(this.el)
    editor.setAttribute("aria-controls", this.el.id)
    editor.setAttribute("aria-haspopup", "listbox")
    for (let node: HTMLElement | null = editor; node; node = node.parentElement) this.ancestors.push(node)
    document.addEventListener("scroll", this.onScroll, true)
    window.addEventListener("resize", this.position)
    window.visualViewport?.addEventListener("resize", this.position)
    window.visualViewport?.addEventListener("scroll", this.position)
    if (typeof ResizeObserver !== "undefined") {
      this.observer = new ResizeObserver(this.position)
      this.ancestors.forEach((node) => this.observer!.observe(node))
    }
  }

  update(props: SuggestionProps<SlashItem>) {
    const previous = this.state.kind === "open" ? this.state.props : undefined
    this.state = { kind: "open", props }
    if (!previous || previous.query !== props.query) this.selectedIndex = 0
    this.selectedIndex = Math.min(this.selectedIndex, Math.max(0, props.items.length - 1))
    this.el.replaceChildren()
    this.rows = props.items.map((item, index) => {
      const row = document.createElement("button")
      row.type = "button"
      row.tabIndex = -1
      row.id = `${this.el.id}-${index}`
      row.className = "slash-menu-item"
      row.setAttribute("role", "option")
      const label = document.createElement("span")
      label.textContent = item.label
      const hint = document.createElement("span")
      hint.className = "slash-menu-hint"
      hint.textContent = item.hint
      row.append(label, hint)
      row.addEventListener("pointermove", () => this.highlight(index, false))
      row.addEventListener("pointerdown", (event) => {
        if (event.pointerType === "mouse") event.preventDefault()
      })
      row.addEventListener("mousedown", (event) => event.preventDefault())
      row.addEventListener("click", () => this.select(index))
      this.el.appendChild(row)
      return row
    })
    if (!props.items.length) {
      const empty = document.createElement("div")
      empty.className = "slash-menu-empty"
      empty.setAttribute("role", "status")
      empty.textContent = "No blocks match"
      this.el.appendChild(empty)
    }
    this.highlight(this.selectedIndex, false)
    this.position()
  }

  private highlight(index: number, reveal: boolean) {
    this.selectedIndex = index
    this.rows.forEach((row, i) => {
      row.classList.toggle("selected", i === index)
      row.setAttribute("aria-selected", String(i === index))
    })
    const row = this.rows[index]
    if (row && !this.el.hidden) this.editor.setAttribute("aria-activedescendant", row.id)
    else this.editor.removeAttribute("aria-activedescendant")
    if (reveal && row) {
      const top = row.offsetTop
      const bottom = top + row.offsetHeight
      if (top < this.el.scrollTop) this.el.scrollTop = top
      else if (bottom > this.el.scrollTop + this.el.clientHeight) this.el.scrollTop = bottom - this.el.clientHeight
    }
  }

  private onScroll = (event: Event) => {
    if (event.target instanceof Node && this.el.contains(event.target)) return
    this.position()
  }

  private hide() {
    this.el.hidden = true
    this.editor.setAttribute("aria-expanded", "false")
    this.editor.removeAttribute("aria-activedescendant")
  }

  private position = () => {
    if (this.state.kind !== "open") return
    const rect = this.state.props.clientRect?.()
    if (!rect || !this.editor.isConnected) { this.hide(); return }
    const viewport = window.visualViewport
    const left = viewport?.offsetLeft ?? 0
    const top = viewport?.offsetTop ?? 0
    const right = left + (viewport?.width ?? window.innerWidth)
    const bottom = top + (viewport?.height ?? window.innerHeight)
    let visibleTop = top, visibleBottom = bottom, visibleLeft = left, visibleRight = right
    for (const node of this.ancestors) {
      const css = getComputedStyle(node)
      const bounds = node.getBoundingClientRect()
      if (/(auto|scroll|hidden|clip)/.test(css.overflowY)) {
        visibleTop = Math.max(visibleTop, bounds.top)
        visibleBottom = Math.min(visibleBottom, bounds.bottom)
      }
      if (/(auto|scroll|hidden|clip)/.test(css.overflowX)) {
        visibleLeft = Math.max(visibleLeft, bounds.left)
        visibleRight = Math.min(visibleRight, bounds.right)
      }
    }
    if (rect.bottom <= visibleTop || rect.top >= visibleBottom || rect.right < visibleLeft || rect.left > visibleRight) {
      this.hide(); return
    }
    const margin = 12, gap = 6
    const above = Math.max(0, rect.top - top - margin - gap)
    const below = Math.max(0, bottom - rect.bottom - margin - gap)
    const flip = below < 280 && above > below
    const height = Math.min(280, flip ? above : below)
    if (height <= 0) { this.hide(); return }
    this.el.style.maxHeight = `${height}px`
    this.el.style.maxWidth = `${Math.max(0, right - left - margin * 2)}px`
    this.el.hidden = false
    this.el.style.left = `${Math.max(left + margin, Math.min(rect.left, right - this.el.offsetWidth - margin))}px`
    this.el.style.top = `${Math.max(top + margin, flip ? rect.top - this.el.offsetHeight - gap : rect.bottom + gap)}px`
    this.editor.setAttribute("aria-expanded", "true")
    this.highlight(this.selectedIndex, false)
  }

  onKeyDown({ event }: SuggestionKeyDownProps): boolean {
    if (this.state.kind !== "open" || event.isComposing) return false
    if (event.key === "Escape") { this.dismiss(); return true }
    if (this.el.hidden) return false
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      const count = this.rows.length
      if (count) this.highlight((this.selectedIndex + (event.key === "ArrowDown" ? 1 : count - 1)) % count, true)
      return true
    }
    if (event.key === "Enter") { this.select(this.selectedIndex); return true }
    return false
  }

  private select(index: number) {
    if (this.state.kind !== "open") return
    const props = this.state.props
    const item = props.items[index]
    if (!item) return
    this.destroy()
    this.dismiss()
    props.command(item)
  }

  destroy() {
    this.state = { kind: "closed" }
    document.removeEventListener("scroll", this.onScroll, true)
    window.removeEventListener("resize", this.position)
    window.visualViewport?.removeEventListener("resize", this.position)
    window.visualViewport?.removeEventListener("scroll", this.position)
    this.observer?.disconnect()
    this.el.remove()
    for (const [name, value] of this.previousAttributes) {
      if (value === null) this.editor.removeAttribute(name)
      else this.editor.setAttribute(name, value)
    }
  }
}

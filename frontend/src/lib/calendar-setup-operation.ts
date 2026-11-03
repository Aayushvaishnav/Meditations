let pending = false
const listeners = new Set<() => void>()

export function calendarSetupPending() { return pending }
export function subscribeCalendarSetup(listener: () => void) {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

// Only operation state crosses component lifetimes; credentials stay in the caller
type SetupStart = { state: "busy" } | { state: "started"; finish: () => void }

export function beginCalendarSetup(): SetupStart {
  if (pending) return { state: "busy" }
  pending = true
  listeners.forEach(listener => listener())
  return {
    state: "started",
    finish: () => {
      pending = false
      listeners.forEach(listener => listener())
    },
  }
}

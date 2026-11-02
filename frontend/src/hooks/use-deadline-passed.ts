import { useCallback, useSyncExternalStore } from "react"

// Browser timers use a signed 32-bit delay; re-arm distant deadlines in chunks.
const MAX_DELAY = 2 ** 31 - 1

export function useDeadlinePassed(deadline: number | null): boolean {
  const getSnapshot = useCallback(() => deadline !== null && deadline < Date.now(), [deadline])
  const subscribe = useCallback((onChange: () => void) => {
    if (deadline === null) return () => {}
    const target = deadline
    let timer: ReturnType<typeof setTimeout> | undefined
    function refresh() {
      clearTimeout(timer)
      onChange()
      const remaining = target - Date.now() + 1
      if (remaining > 0) timer = setTimeout(refresh, Math.min(remaining, MAX_DELAY))
    }
    refresh()
    window.addEventListener("focus", refresh)
    document.addEventListener("visibilitychange", refresh)
    return () => {
      clearTimeout(timer)
      window.removeEventListener("focus", refresh)
      document.removeEventListener("visibilitychange", refresh)
    }
  }, [deadline])
  return useSyncExternalStore(subscribe, getSnapshot, () => false)
}

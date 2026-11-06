import type { QueryClient } from "@tanstack/react-query"

export function invalidateTelemetry(qc: QueryClient) {
  return Promise.all([
    qc.invalidateQueries({ queryKey: ["journal-activity"] }),
    qc.invalidateQueries({ queryKey: ["scores-daily"] }),
    qc.invalidateQueries({ queryKey: ["insights"] }),
  ])
}

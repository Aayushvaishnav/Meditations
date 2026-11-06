import { createContext, useContext } from "react"
import type { Task, TaskList } from "@/api/types"

export type BulkContext = {
  tasks: Task[]; eligible: Task[]; lists: TaskList[]
  active: boolean; setActive: (value: boolean) => void
  selected: Set<string>; setSelected: React.Dispatch<React.SetStateAction<Set<string>>>
  pending: boolean; setPending: (value: boolean) => void
}
export const BulkSelectionContext = createContext<BulkContext | undefined>(undefined)


export function useBulkSelecting(): boolean {
  return useContext(BulkSelectionContext)?.active ?? false
}

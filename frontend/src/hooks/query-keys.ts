import { tasksKey } from "./task-cache"

export const qk = {
  tasks: tasksKey,
  lists: ["lists"] as const,
  timeBlocks: ["time-blocks"] as const,
  health: ["health"] as const,
}

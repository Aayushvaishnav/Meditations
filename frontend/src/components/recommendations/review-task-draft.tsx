import { useId, useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useCreateTask } from "@/hooks/api"

export function ReviewTaskDraft({ day, recommendation }: { day: string; recommendation: string }) {
  const id = useId()
  const createTask = useCreateTask()
  const submitting = useRef(false)
  const [stage, setStage] = useState<"suggested" | "editing" | "created">("suggested")
  const [title, setTitle] = useState(recommendation.trim().slice(0, 500))
  const [deadline, setDeadline] = useState("")
  const [error, setError] = useState<string | false>(false)

  return (
    <div className="mt-4 space-y-3 border-t pt-3">
      <p className="text-sm leading-relaxed break-words">{recommendation}</p>
      {stage === "created" ? <p role="status" className="text-sm text-muted-foreground">Task created</p> :
        stage === "suggested" ? <Button variant="outline" size="sm" onClick={() => setStage("editing")}>Draft task</Button> : (
          <form className="max-w-xl space-y-3" onSubmit={async event => {
            event.preventDefault()
            if (submitting.current || stage !== "editing") return
            if (!title.trim()) {
              setError("Enter a task title before creating the task.")
              return
            }
            submitting.current = true
            setError(false)
            try {
              await createTask.mutateAsync({
                title: title.trim(),
                description: `Follow-up from daily review ${day}\n\n${recommendation}`,
                deadline: deadline ? { kind: "date", date: deadline } : { kind: "none" },
              })
              setStage("created")
            } catch {
              setError("Couldn't create the task. Check your connection, then select Create task to retry.")
            } finally {
              submitting.current = false
            }
          }}>
            <div className="space-y-1.5">
              <label htmlFor={`${id}-title`} className="text-sm font-medium">Task title</label>
              <Input id={`${id}-title`} autoFocus required maxLength={500} value={title} disabled={createTask.isPending}
                aria-describedby={error ? `${id}-error` : undefined} aria-invalid={Boolean(error)}
                onChange={event => setTitle(event.target.value)} />
            </div>
            <div className="space-y-1.5">
              <label htmlFor={`${id}-deadline`} className="text-sm font-medium">Deadline (optional calendar date)</label>
              <Input id={`${id}-deadline`} type="date" min="0001-01-01" max="9999-12-31" value={deadline} disabled={createTask.isPending}
                onChange={event => setDeadline(event.target.value)} />
            </div>
            {error && <p id={`${id}-error`} role="alert" className="text-sm text-destructive">{error}</p>}
            <div className="flex flex-wrap gap-2">
              <Button type="submit" size="sm" disabled={createTask.isPending}>{createTask.isPending ? "Creating task…" : "Create task"}</Button>
              <Button type="button" variant="ghost" size="sm" disabled={createTask.isPending} onClick={() => { setStage("suggested"); setError(false) }}>Cancel</Button>
            </div>
          </form>
        )}
    </div>
  )
}

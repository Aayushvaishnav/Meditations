import { useUi, type ScoreDisplay } from "@/stores/ui"

export function ScoreDisplayPreference() {
  const display = useUi((s) => s.scoreDisplay)
  const setDisplay = useUi((s) => s.setScoreDisplay)
  return (
    <div className="space-y-2">
      <label className="block text-sm font-medium" htmlFor="score-display">Score display</label>
      <select
        id="score-display"
        aria-describedby="score-display-help"
        value={display}
        onChange={(event) => setDisplay(event.target.value as ScoreDisplay)}
        className="min-h-11 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
      >
        <option value="scored">Show scores</option>
        <option value="reflection">Reflection-first</option>
      </select>
      <p id="score-display-help" className="text-xs leading-relaxed text-muted-foreground">
        Reflection-first hides numeric scores, score charts and score trends in Journal and Insights.
        Mood, energy, focus, activity and written reflections stay visible. This preference is saved on this device;
        reviews and stored scores stay unchanged. Written reflections may still mention numbers.
      </p>
    </div>
  )
}

export function ScoreExplanation() {
  return (
    <details className="mt-2 text-xs leading-relaxed text-muted-foreground">
      <summary className="pointer-coarse:min-h-11 w-fit cursor-pointer rounded-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">How scoring works</summary>
      <p className="mt-2 max-w-prose">
        Tasks contribute up to 40 points, focus up to 35 and habits up to 15.
        When all three components reach 100%, they total 90 points before the AI nudge.
        An AI review can add or subtract up to 10 points; the final score stays between 0 and 100.
        A 90-point result before review reflects full component completion.
      </p>
      <p className="mt-2 max-w-prose">
        Days without scheduled habits receive the full habit component. A disabled focus target receives
        the full focus component. Days without planned or completed tasks receive zero task points.
      </p>
    </details>
  )
}

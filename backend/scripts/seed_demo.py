"""Seed a synthetic month of journal + task data for testing the AI features.

Wipes the data tables (lists, tasks, focus sessions, habits, journal entries
and all AI rollups) in the target database — `app_settings` and `ai_usage` are
preserved — then generates 5 weeks (Mon 2026-08-10 → Sun 2026-09-13 by
default) of realistic, narratively consistent data:

  week 1  strong start        high completion, 4-5h deep work, mood 4
  week 2  dip                 neighbor renovation noise, prod incident, one
                              skipped journal day, missed habits
  week 3  recovery            started running, Lisbon trip planning, dentist
  week 4  strong              interview prep, Atlas migration to staging
  week 5  winding down        leadership demo, 5K run, live "today" with
                              overdue work + tasks due today for the briefing

`daily_scores` / `weekly_summaries` / `monthly_summaries` are deliberately left
empty: they are outputs of the AI review agents, so the full AI pipeline can be
exercised from scratch (daily review upserts over any row).

Usage (from backend/):
    uv run python scripts/seed_demo.py                  # default window, embeds
    uv run python scripts/seed_demo.py --no-embed       # FTS only, no model download
    uv run python scripts/seed_demo.py --db data/demo.db --start 2026-08-01 --end 2026-08-31
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import sys
from dataclasses import dataclass, field
from datetime import date as Date
from datetime import datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # direct-script runs

from sqlalchemy import text  # noqa: E402

from app import db, search  # noqa: E402
from app.models import (  # noqa: E402
    FocusSession,
    Habit,
    HabitLog,
    JournalEntry,
    Task,
    TaskList,
)
from app.scoring import compute_daily_score  # noqa: E402
from app.telemetry import collect_daily_metrics  # noqa: E402
from app.util import monday_of, new_id  # noqa: E402

# --- window / phase config ----------------------------------------------------
PHASES = ("strong", "dip", "recovery", "strong", "wind")  # one per ISO week
SKIP_JOURNAL_DAYS = {Date(2026, 8, 20)}  # missed day — weekly agent sees 6/7
MOOD_NONE_DAYS = {Date(2026, 8, 15)}  # UI edge: text but no mood
ENERGY_NONE_DAYS = {Date(2026, 9, 6)}

FOCUS_MINUTES = {  # per-day deep-work target vs their 5.0h setting
    "strong": (230, 320),
    "dip": (25, 95),
    "recovery": (150, 260),
    "wind": (130, 280),
}
HABIT_RATE = {  # completion probability per phase
    "strong": 0.88,
    "dip": 0.4,
    "recovery": 0.72,
    "wind": 0.82,
}

LISTS = [
    ("Work", "#3b82f6", "briefcase", True),
    ("Personal", "#22c55e", "home", True),
    ("Health", "#ef4444", "heart", False),
    ("Learning", "#a855f7", "book-open", False),
]

HABITS = [
    ("Morning meditation", Date(2026, 8, 10)),
    ("Read 20 pages", Date(2026, 8, 10)),
    ("Lights out by 11:30", Date(2026, 8, 10)),
    ("Morning run", Date(2026, 8, 24)),  # mid-month: exercises created_at gating
]
RUN_WEEKDAYS = {0, 2, 5}  # Mon/Wed/Sat (date.weekday())

# --- task authoring -------------------------------------------------------------
@dataclass
class TaskSpec:
    key: str
    title: str
    list_key: str
    priority: int = 0
    tags: list[str] = field(default_factory=list)
    est: int | None = None
    due: str | None = None
    done: str | None = None
    parent: str | None = None
    note: str | None = None  # first-person journal phrase used on the done day
    in_progress: bool = False


TASKS = [
    # Work — Atlas migration arc
    TaskSpec("design-doc", "Write Atlas migration design doc", "Work", 3, ["deep-work"], 120, "2026-08-12", "2026-08-11", note="the Atlas design doc finally went out for review"),
    TaskSpec("diff-tool", "Implement schema diff tool for Atlas", "Work", 3, ["deep-work"], 180, "2026-08-14", "2026-08-14", note="the schema diff tool is working end to end"),
    TaskSpec("dry-run", "Dry-run the Atlas demo for the team", "Work", 2, [], 45, "2026-08-14", "2026-08-14", note="the demo dry-run got friendly feedback"),
    TaskSpec("flaky-tests", "Fix flaky integration tests", "Work", 2, ["tech-debt"], 90, "2026-08-24", "2026-08-25", note="the flaky integration tests are finally green"),
    TaskSpec("handoff", "Write on-call handoff notes", "Work", 2, ["admin"], 30, "2026-08-19", "2026-08-19", note="the on-call handoff notes"),
    TaskSpec("postmortem", "Postmortem doc for the prod incident", "Work", 3, ["deep-work"], 90, "2026-08-21", "2026-08-21", note="the blameless postmortem"),
    TaskSpec("runbooks", "Update Atlas runbooks", "Work", 1, ["admin"], 45, "2026-08-26", "2026-08-26", note="the runbook updates"),
    TaskSpec("pr-batch", "Review Priya's PR batch", "Work", 1, [], 40, "2026-08-27", "2026-08-27", note="Priya's PR batch"),
    TaskSpec("cutover-sync", "Sync with the platform team on cutover windows", "Work", 2, [], 30, "2026-08-28", "2026-08-28", note="cutover windows agreed with the platform team"),
    TaskSpec("checklist", "Prep the cutover checklist", "Work", 2, [], 45, "2026-09-02", "2026-09-02", note="the cutover checklist"),
    TaskSpec("cold-starts", "Investigate slow cold starts on staging", "Work", 1, [], 60, None, "2026-09-02", note="the cold-start investigation"),
    TaskSpec("ship-staging", "Ship Atlas migration to staging", "Work", 3, ["deep-work"], 240, "2026-09-07", "2026-09-07", note="the staging rollout of Atlas"),
    TaskSpec("load-test", "Load-test staging after the migration", "Work", 2, [], 60, "2026-09-08", "2026-09-08", note="the load test — numbers look healthy"),
    TaskSpec("1on1", "One-on-one notes for the team", "Work", 1, ["admin"], 30, "2026-09-09", "2026-09-09", note="one-on-one notes"),
    TaskSpec("demo-parent", "Prep the leadership demo", "Work", 3, ["deep-work"], None, "2026-09-11", "2026-09-11", note="the leadership demo"),
    TaskSpec("demo-dashboard", "Build the latency comparison dashboard", "Work", 2, ["deep-work"], 90, "2026-09-09", "2026-09-09", parent="demo-parent", note="the latency dashboard"),
    TaskSpec("demo-slides", "Write the demo slides", "Work", 2, [], 60, "2026-09-10", "2026-09-10", parent="demo-parent"),
    TaskSpec("demo-rehearse", "Rehearse the demo end to end", "Work", 1, [], 20, "2026-09-11", "2026-09-11", parent="demo-parent"),
    TaskSpec("archive-branch", "Archive the old Atlas staging branch", "Work", 1, ["admin"], 15, "2026-09-12", "2026-09-12", note="branch cleanup"),
    TaskSpec("metrics-collector", "Refactor metrics collector", "Work", 2, ["tech-debt"], 120, "2026-09-04", None, in_progress=True),
    TaskSpec("vendor-email", "Reply to vendor email about license renewal", "Work", 1, ["admin"], 15, "2026-09-08", "2026-09-10"),
    TaskSpec("wiki-tidy", "Tidy the team wiki index", "Work", 1, ["admin"], 30, "2026-09-08", "2026-09-08"),
    TaskSpec("oncall-sheet", "Update the on-call rotation sheet", "Work", 1, ["admin"], 20, "2026-09-10", "2026-09-10"),
    TaskSpec("quarterly", "Draft quarterly planning notes", "Work", 2, ["deep-work"], 60, "2026-09-15", None),
    TaskSpec("feature-flags", "Clean up feature flags after the Atlas rollout", "Work", 1, [], 30, "2026-09-16", None),
    # Personal — Lisbon trip + family
    TaskSpec("lisbon", "Plan the Lisbon trip (Oct 3-10)", "Personal", 2, ["trip"], None, "2026-08-29", "2026-08-29", note="Lisbon planning"),
    TaskSpec("lisbon-flights", "Compare flights to Lisbon", "Personal", 2, ["trip"], 45, "2026-08-25", "2026-08-25", parent="lisbon"),
    TaskSpec("lisbon-room", "Book the apartment in Alfama", "Personal", 2, ["trip"], 30, "2026-08-27", "2026-08-27", parent="lisbon"),
    TaskSpec("lisbon-sintra", "Research Sintra day-trip options", "Personal", 1, ["trip"], 30, "2026-08-30", "2026-08-30", parent="lisbon"),
    TaskSpec("maya-gift", "Pick a birthday gift for Maya", "Personal", 2, ["family"], 45, "2026-08-21", "2026-08-21", note="a birthday gift for Maya"),
    TaskSpec("maya-dinner", "Book a table for Maya's birthday dinner", "Personal", 2, ["family"], 15, "2026-08-22", "2026-08-21"),
    TaskSpec("noise-complaint", "Talk to the building manager about the noise", "Personal", 2, [], 30, "2026-08-18", "2026-08-19", note="the conversation with the building manager"),
    TaskSpec("earplugs", "Buy proper noise-cancelling earplugs", "Personal", 1, [], 20, "2026-08-19", "2026-08-19", note="new earplugs"),
    TaskSpec("passport", "Renew passport", "Personal", 2, ["admin"], 60, "2026-09-05", None),
    TaskSpec("insurance", "Pay the apartment insurance", "Personal", 1, ["admin"], 15, "2026-09-12", "2026-09-12"),
    TaskSpec("backup", "Backup the laptop", "Personal", 1, ["admin"], 45, None, "2026-09-05", note="the laptop backup"),
    TaskSpec("photos", "Sort photos from the last months", "Personal", 1, [], 45, None, "2026-09-06", note="photo sorting"),
    TaskSpec("bike", "Fix bike brakes", "Personal", 1, [], 45, None, None),
    TaskSpec("week-plan", "Plan the week ahead", "Personal", 2, [], 30, "2026-09-13", None),
    # Health
    TaskSpec("dentist-book", "Book a dentist checkup", "Health", 2, ["health"], 15, "2026-08-25", "2026-08-25"),
    TaskSpec("shoes", "Order new running shoes", "Health", 1, ["health"], 20, "2026-08-26", "2026-08-26", note="new running shoes"),
    TaskSpec("dentist-visit", "Dentist appointment — filling", "Health", 2, ["health"], 60, "2026-08-27", "2026-08-27", note="the dentist — one small filling, no drama"),
    TaskSpec("physical", "Schedule the annual physical", "Health", 2, ["health"], 15, "2026-09-10", None),
    TaskSpec("eyes", "Update the eye prescription", "Health", 1, ["health"], 30, "2026-09-30", None),
    # Learning
    TaskSpec("habits-1", "Atomic Habits: chapters 1-4", "Learning", 1, ["reading"], 60, "2026-08-16", "2026-08-15", note="the first chapters of Atomic Habits"),
    TaskSpec("habits-2", "Atomic Habits: chapters 5-8", "Learning", 1, ["reading"], 60, "2026-08-23", "2026-08-23", note="the habit-stacking chapter"),
    TaskSpec("habits-3", "Atomic Habits: chapters 9-12", "Learning", 1, ["reading"], 60, "2026-08-30", "2026-08-30"),
    TaskSpec("habits-done", "Finish Atomic Habits", "Learning", 1, ["reading"], 60, "2026-09-06", "2026-09-06", note="Atomic Habits — done, cover to cover"),
    TaskSpec("pragmatic", "Start The Pragmatic Programmer", "Learning", 1, ["reading"], 45, "2026-09-13", None),
    TaskSpec("prep-notes", "Prep Northwind systems-design notes", "Learning", 2, ["interview"], 60, "2026-09-01", "2026-09-01", note="the systems-design prep notes"),
    TaskSpec("takehome-plan", "Draft the Northwind take-home plan", "Learning", 2, ["interview"], 45, "2026-09-03", "2026-09-03", note="the take-home plan"),
    TaskSpec("cutover-announce", "Send the Atlas cutover announcement", "Work", 2, ["admin"], 20, "2026-09-04", "2026-09-04", note="the cutover announcement"),
    TaskSpec("ts-generics", "TypeScript generics course: module 3", "Learning", 2, ["learning"], 90, "2026-08-27", "2026-08-29", note="the TypeScript generics module"),
    TaskSpec("dashboard-spike", "Side-project spike: dashboard for home sensors", "Learning", 1, ["side-project"], 120, None, "2026-08-16", note="a dashboard spike for the home sensors"),
]

# Notes already woven into that day's handwritten event paragraph.
EVENT_COVERED: dict[Date, set[str]] = {
    Date(2026, 8, 14): {"dry-run", "diff-tool"},
    Date(2026, 8, 25): {"flaky-tests", "lisbon-flights"},
    Date(2026, 8, 27): {"dentist-visit", "lisbon-room"},
    Date(2026, 8, 28): {"cutover-sync"},
    Date(2026, 8, 29): {"lisbon", "lisbon-sintra"},
    Date(2026, 9, 11): {"demo-parent", "demo-rehearse"},
}

# --- handwritten anchor events (Q&A ground truth) -------------------------------
EVENTS: dict[Date, str] = {
    Date(2026, 8, 10): (
        "Wrote down the goals for the month over morning coffee: ship the Atlas migration demo by "
        "the 21st, run three times a week, and actually finish Atomic Habits instead of letting it "
        "glare at me from the nightstand. Started the book tonight — the systems-vs-goals idea is "
        "obvious in hindsight, which is probably why it stings."
    ),
    Date(2026, 8, 13): (
        "Coffee with Sam in the morning turned into a two-hour detour about side projects and job "
        "stuff. Worth every minute — I came back with three ideas for the dashboard spike and zero "
        "regret about the lost morning."
    ),
    Date(2026, 8, 14): (
        "Demo dry-run went better than I deserved given the prep. The schema diff tool behaved, the "
        "small audience asked friendly questions, and for the first time the migration story feels "
        "tellable end to end. Week one of the month plan: essentially intact."
    ),
    Date(2026, 8, 16): (
        "Spent a happy afternoon on the home-sensor dashboard spike — nothing production-grade, just "
        "the fun kind of plumbing. Finished chapter 4 of Atomic Habits; the two-minute rule is "
        "already earning its keep on the reading habit."
    ),
    Date(2026, 8, 17): (
        "The apartment above mine decided this is the week for renovation. Drilling from 7am sharp. "
        "I worked with earplugs in and still lost the thread every time the hammer started. Mood: "
        "gravel. If this keeps up I'm talking to the building manager."
    ),
    Date(2026, 8, 19): (
        "Production incident at 11:00, on-call, the whole circus. We contained it by 15:00 and "
        "nobody lost data, but my brain is soup. Writing this from bed. Tomorrow will be admin and "
        "apologies, not deep work."
    ),
    Date(2026, 8, 22): (
        "Maya's birthday dinner — the good kind of loud. She loved the gift, which was a relief "
        "because I second-guessed it three times at the register. Home by midnight, tired in the "
        "warm way."
    ),
    Date(2026, 8, 24): (
        "First run of the plan: Couch to 5K, week 1 day 1. Ninety seconds of jogging felt like a "
        "hostage situation, but I finished it and logged the new morning-run habit. Legs have filed "
        "a formal complaint."
    ),
    Date(2026, 8, 25): (
        "Compared flights to Lisbon tonight — October 3rd to 10th is locked in my head, just need to "
        "click buy. And the flaky integration tests are finally green after ninety minutes of "
        "unglamorous log-reading. Sometimes the boring fix is the whole fix."
    ),
    Date(2026, 8, 27): (
        "Dentist at 16:00 — one small filling, no drama, and Dr. Iyer confirmed the headaches aren't "
        "jaw-related, which I'd been quietly worrying about. Booked the Alfama apartment for Lisbon "
        "right after; it has a tiny balcony and I'm already planning morning coffee there."
    ),
    Date(2026, 8, 28): (
        "Bought the flights. Lisbon, October 3-10. It felt extravagant for about four minutes and "
        "then it just felt right. The platform team also agreed on cutover windows today, so Atlas "
        "has a runway and I have a horizon."
    ),
    Date(2026, 8, 29): (
        "Trip planning is officially wrapped: flights, apartment, and a shortlist of Sintra day "
        "trips. There is a specific satisfaction in closing a parent task with every subtask green."
    ),
    Date(2026, 8, 31): (
        "First-of-the-month energy. Also: a recruiter from Northwind emailed about a staff engineer "
        "role. I'm not job hunting, exactly, but I replied. Curious more than anything."
    ),
    Date(2026, 9, 1): (
        "Started proper interview prep for Northwind: an hour of systems-design reading before "
        "lunch. Treating it as free education even if nothing comes of it."
    ),
    Date(2026, 9, 3): (
        "Call with the Northwind recruiter went well — forty minutes, honest questions in both "
        "directions. Not saying yes to anything, but prepping properly is now a thing I'm doing. "
        "Their take-home is apparently a systems-design exercise, which suits me."
    ),
    Date(2026, 9, 6): (
        "Finished Atomic Habits tonight. The last third is repetitive, but make-it-obvious, "
        "make-it-easy is a keeper. Next up: The Pragmatic Programmer, which has been waiting "
        "patiently on the shelf."
    ),
    Date(2026, 9, 7): (
        "Atlas migration is live on staging. Load numbers held, the dashboards look like a textbook, "
        "and the team did a small cake thing in the kitchen. Months of grind compressed into one "
        "quiet afternoon of 'huh, it worked.'"
    ),
    Date(2026, 9, 11): (
        "Leadership demo. Slides held up, the latency dashboard made the point better than any bullet "
        "could, and someone said 'this is the clearest migration story I've seen' — I'll be riding "
        "that sentence for a week. The rehearsal paid off."
    ),
    Date(2026, 9, 12): (
        "Ran 5K without walk breaks. Slow, ugly, complete. Spent the afternoon doing nothing in "
        "particular, which after this month feels earned."
    ),
    Date(2026, 9, 13): (
        "Sunday morning, journal and coffee before the week starts. The month in review: started "
        "strong, hit a wall in week two (noise, sleep, an incident), climbed out with running and "
        "the trip plans, and finished with Atlas shipped and a demo I'm proud of. This week: "
        "quarterly planning notes, the passport renewal I keep postponing, and a decision about "
        "Northwind."
    ),
}

# Special-case entries that replace the composed body entirely: date -> (text, mood, energy).
MICRO_ENTRIES: dict[Date, tuple[str, int, int]] = {
    Date(2026, 8, 19): ("Production incident, contained by 15:00. Brain is soup. Bed.", 2, 1),
    Date(2026, 9, 9): (
        "Headache since morning, the dull kind behind the eyes. Left at 15:00 after the one-on-ones. "
        "Screens made it worse; tonight is a book and early lights.",
        2,
        2,
    ),
}

MOOD_OVERRIDES = {Date(2026, 8, 22): 5, Date(2026, 9, 11): 5, Date(2026, 8, 24): 4}
ENERGY_OVERRIDES = {Date(2026, 8, 22): 3, Date(2026, 9, 11): 4, Date(2026, 8, 24): 3}
MORNING_ENTRIES = {Date(2026, 9, 13)}  # today's entry is written in the morning

# --- prose banks -----------------------------------------------------------------
OPENERS = {
    "strong": [
        "Good, focused day.",
        "One of those days where the plan survived contact with reality.",
        "Woke up before the alarm, which set the tone.",
        "Momentum from yesterday carried over nicely.",
        "Solid, unglamorous, productive.",
    ],
    "dip": [
        "Foggy and slow today.",
        "Another rough night — the renovation noise starts at 7am sharp.",
        "Running on fumes.",
        "Barely got moving today, and everything took twice as long.",
        "Short temper, short attention span.",
    ],
    "recovery": [
        "Slowly climbing back.",
        "Energy is coming back, piece by piece.",
        "Better day. Not dramatic, just steady.",
        "Felt like myself for a few hours today, which was nice.",
        "Small win: got outside before opening the laptop.",
    ],
    "wind": [
        "Steady, satisfying day.",
        "Good rhythm this week.",
        "Quiet confidence today — things are landing.",
        "The week is humming.",
        "Tired, but the good kind of tired.",
    ],
}
WORK_SENTENCES = [
    "Main outcome: {note}.",
    "Biggest relief of the day: {note}.",
    "Also {note}, which had been hanging over me.",
    "Crossed a line off the list: {note}.",
    "The headline: {note}.",
    "Quietly satisfying: {note}.",
    "Spent the deep-work block on it and {note}.",
    "Wrapping the day with {note} done and dusted.",
]
REFLECTIONS = [
    "Energy dipped hard after lunch; I should stop pretending a third coffee fixes that.",
    "I procrastinate exactly when a task has no clear first step. Naming the first step helps.",
    "The 5pm slump is real, but a twenty-minute walk rescued the evening.",
    "Screens after 23:00 are stealing sleep; the lights-out rule needs teeth.",
    "Reading before bed instead of scrolling felt noticeably better.",
    "Sleep is the whole game. Everything is easier on seven and a half hours.",
    "I keep overestimating what fits into an afternoon. Worth remembering when planning.",
    "Small systems beat motivation. Tonight proved it again.",
]
TOMORROWS = [
    "Tomorrow: protect the morning deep-work block and nothing else matters.",
    "Tomorrow is planned light by design.",
    "Tomorrow has one job. Everything else is bonus.",
    "Aiming for an earlier start tomorrow.",
    "Tomorrow I want to finish what I started before opening anything new.",
    "No grand plans for tomorrow; consistency over intensity.",
]
RAN_LINES = [
    "Morning run done before the day had opinions.",
    "Ran this morning — legs objected, I went anyway.",
    "Run streak intact. Cold start, warm finish.",
]


# --- helpers ---------------------------------------------------------------------
def at(day: Date, hh: int, mm: int = 0) -> datetime:
    return datetime.combine(day, time(hh, mm))  # naive UTC, per convention


def phase_of(day: Date, start: Date) -> str:
    return PHASES[min((day - start).days // 7, len(PHASES) - 1)]


def d(iso: str) -> Date:
    return Date.fromisoformat(iso)


# --- wipe --------------------------------------------------------------------------
WIPE_ORDER = (
    "habit_logs",
    "habits",
    "focus_sessions",
    "tasks",
    "lists",
    "journal_entries",
    "daily_scores",
    "weekly_summaries",
    "monthly_summaries",
)


async def wipe_data(session) -> dict[str, int]:
    """Delete all seeded data (never app_settings / ai_usage). Returns per-table counts."""
    counts: dict[str, int] = {}
    for table in WIPE_ORDER:
        counts[table] = (await session.exec(text(f"SELECT COUNT(*) FROM {table}"))).scalar_one()
        await session.exec(text(f"DELETE FROM {table}"))
    for table in ("fts_entries", "vec_entries"):
        try:
            await session.exec(text(f"DELETE FROM {table}"))
        except Exception:  # noqa: BLE001 — search tables may not exist yet
            pass
    await session.commit()
    return counts


# --- builders -----------------------------------------------------------------------
def build_lists(rng: random.Random) -> dict[str, TaskList]:
    lists: dict[str, TaskList] = {}
    for i, (name, color, icon, fav) in enumerate(LISTS):
        lists[name] = TaskList(
            id=new_id(), name=name, color=color, icon=icon, is_favorite=fav,
            created_at=at(Date(2026, 8, 1), 9, i),
        )
    return lists


def build_recurring() -> list[TaskSpec]:
    """Weekly review (Mondays) and gym sessions (Tue/Thu) as per-occurrence rows."""
    specs: list[TaskSpec] = []
    day = Date(2026, 8, 10)
    while day <= Date(2026, 9, 14):  # one future Monday, still todo
        done = day if day < Date(2026, 9, 14) else None
        specs.append(TaskSpec(
            f"weekly-review-{day.isoformat()}", "Weekly review", "Personal", 2, ["review"], 30,
            due=day.isoformat(), done=done.isoformat() if done else None,
        ))
        day += timedelta(days=7)
    day = Date(2026, 8, 11)
    while day <= Date(2026, 9, 10):
        done = "2026-08-22" if day == Date(2026, 8, 20) else day.isoformat()  # makeup session after the bad week
        specs.append(TaskSpec(
            f"gym-{day.isoformat()}", "Gym session", "Health", 1, ["health"], 60,
            due=day.isoformat(), done=done,
        ))
        day += timedelta(days=2 if day.weekday() == 1 else 5)  # Tue -> Thu -> Tue
    return specs


def build_tasks(rng: random.Random, lists: dict[str, TaskList]) -> tuple[list[Task], dict[Date, list[Task]]]:
    tasks: list[Task] = []
    id_by_key: dict[str, str] = {}
    order = {name: 1000.0 for name in lists}
    child_order: dict[str, float] = {}

    for spec in TASKS + build_recurring():
        due = at(d(spec.due), rng.choice([9, 12, 17])) if spec.due else None
        if spec.due and spec.key.startswith("gym-"):
            due = at(d(spec.due), 18, 30)
        if spec.due and spec.key.startswith("weekly-review"):
            due = at(d(spec.due), 17, 0)

        created = at(d(spec.due), rng.randint(8, 20), rng.randint(0, 59)) - timedelta(days=rng.randint(1, 5)) if spec.due else at(Date(2026, 8, 9), 12)
        if created < at(Date(2026, 8, 1), 9):
            created = at(Date(2026, 8, 1), 9)

        done_at = None
        if spec.done:
            # mostly evenings, sometimes midday; gym right after its 18:30 slot
            if spec.key.startswith("gym-"):
                done_at = at(d(spec.done), 19, 15)
            elif spec.key.startswith("weekly-review"):
                done_at = at(d(spec.done), rng.randint(19, 21), rng.choice([0, 15, 30, 45]))
            else:
                r = rng.random()
                hh = rng.randint(10, 13) if r < 0.25 else (rng.randint(14, 17) if r < 0.5 else rng.randint(18, 22))
                done_at = at(d(spec.done), hh, rng.choice([0, 10, 20, 30, 40, 50]))
            if done_at < created:
                done_at = created + timedelta(hours=2)

        list_id = None if spec.parent else lists[spec.list_key].id
        parent_id = id_by_key.get(spec.parent) if spec.parent else None
        if parent_id:
            child_order[parent_id] = child_order.get(parent_id, 0.0) + 10.0
            order_index = child_order[parent_id]
        else:
            order_index = order[spec.list_key]
            order[spec.list_key] += 1000.0

        task = Task(
            id=new_id(),
            list_id=list_id,
            parent_id=parent_id,
            title=spec.title,
            priority=spec.priority,
            status="completed" if spec.done else ("in_progress" if spec.in_progress else "todo"),
            due_date=due,
            estimated_minutes=spec.est,
            actual_minutes=(spec.est or rng.randint(20, 90)) if spec.done else 0,
            tags=spec.tags,
            order_index=order_index,
            completed_at=done_at,
            created_at=created,
            updated_at=done_at or created,
        )
        id_by_key[spec.key] = task.id
        tasks.append(task)

    by_day: dict[Date, list[Task]] = {}
    for t in tasks:
        if t.completed_at:
            by_day.setdefault(t.completed_at.date(), []).append(t)
    return tasks, by_day


def build_focus(rng: random.Random, day: Date, phase: str, done_tasks: list[Task]) -> list[FocusSession]:
    if day == Date(2026, 9, 13):  # today: one planning pomodoro so far
        return [FocusSession(id=new_id(), duration_minutes=25, created_at=at(day, 10, 0))]
    if day.weekday() >= 5:  # weekends: light side-project/reading time
        if rng.random() < 0.5:
            return [FocusSession(id=new_id(), duration_minutes=rng.choice([25, 50]), session_type="stopwatch", created_at=at(day, rng.randint(10, 16)))]
        return []

    lo, hi = FOCUS_MINUTES[phase]
    target = rng.randint(lo, hi)
    sessions: list[FocusSession] = []
    clock = at(day, rng.choice([8, 9, 9, 10]), rng.choice([0, 15, 30, 45]))
    while target > 0 and clock.hour < 20:
        take = min(50 if rng.random() < 0.6 else 25, target)
        linked = rng.choice(done_tasks).id if done_tasks and rng.random() < 0.7 else None
        sessions.append(FocusSession(
            id=new_id(), task_id=linked, duration_minutes=take,
            session_type="pomodoro", created_at=clock,
            notes=None,
        ))
        clock += timedelta(minutes=take + rng.choice([10, 15]))
        target -= take
    return sessions


def build_habits(rng: random.Random, start: Date, end: Date) -> tuple[list[Habit], list[HabitLog], set[Date]]:
    habits = [Habit(id=new_id(), name=name, target_frequency="daily", created_at=at(created, 7, 0)) for name, created in HABITS]
    logs: list[HabitLog] = []
    run_days: set[Date] = set()
    day = start
    while day <= end:
        for habit in habits:
            if habit.created_at.date() > day:
                continue
            if habit.name == "Morning run":
                if day.weekday() in RUN_WEEKDAYS and rng.random() < 0.8 and day >= Date(2026, 8, 24):
                    logs.append(HabitLog(id=new_id(), habit_id=habit.id, date=day, completed=True))
                    run_days.add(day)
                continue
            if rng.random() < HABIT_RATE[phase_of(day, start)]:
                logs.append(HabitLog(id=new_id(), habit_id=habit.id, date=day, completed=True))
        day += timedelta(days=1)
    return habits, logs, run_days


def compose_entry(rng: random.Random, day: Date, phase: str, notes: list[str], run_today: bool) -> str:
    parts: list[str] = [rng.choice(OPENERS[phase])]
    if run_today:
        parts.append(rng.choice(RAN_LINES))
    covered = EVENT_COVERED.get(day, set())
    extra = [n for n in notes if n not in covered]
    if day in EVENTS:
        parts.append(EVENTS[day])
        if len(extra) >= 2:
            parts.append(rng.choice(WORK_SENTENCES).format(note=extra[0]))
    else:
        if extra:
            picked = extra[: rng.randint(1, min(2, len(extra)))]
            for note in picked:
                parts.append(rng.choice(WORK_SENTENCES).format(note=note))
        if rng.random() < 0.6:
            parts.append(rng.choice(REFLECTIONS))
        if rng.random() < 0.45:
            parts.append(rng.choice(TOMORROWS))
    if extra and rng.random() < 0.25:
        bullets = "\n".join(f"- {n[0].upper()}{n[1:]}" for n in extra[:2])
        parts.append(f"**Highlights**\n{bullets}")
    return "\n\n".join(parts)


def mood_energy(rng: random.Random, day: Date, phase: str) -> tuple[int | None, int | None]:
    base = {"strong": (4.0, 4.0), "dip": (2.6, 2.4), "recovery": (3.4, 3.3), "wind": (3.8, 3.6)}[phase]
    mood = max(1, min(5, round(base[0] + rng.uniform(-0.6, 0.6))))
    energy = max(1, min(5, round(base[1] + rng.uniform(-0.6, 0.6))))
    if day in MOOD_OVERRIDES:
        mood = MOOD_OVERRIDES[day]
    if day in ENERGY_OVERRIDES:
        energy = ENERGY_OVERRIDES[day]
    return (None if day in MOOD_NONE_DAYS else mood, None if day in ENERGY_NONE_DAYS else energy)


def build_journal(rng: random.Random, start: Date, end: Date, notes_by_day: dict[Date, list[str]], run_days: set[Date]) -> list[JournalEntry]:
    entries: list[JournalEntry] = []
    day = start
    while day <= end:
        if day in SKIP_JOURNAL_DAYS:
            day += timedelta(days=1)
            continue
        phase = phase_of(day, start)
        if day in MICRO_ENTRIES:
            text_, mood, energy = MICRO_ENTRIES[day]
        else:
            mood, energy = mood_energy(rng, day, phase)
            text_ = compose_entry(rng, day, phase, notes_by_day.get(day, []), day in run_days)
        entries.append(JournalEntry(
            date=day, raw_markdown=text_, mood=mood, energy=energy,
            created_at=at(day, 10, 30) if day in MORNING_ENTRIES else at(day, 21, rng.choice([0, 15, 30, 45])),
        ))
        day += timedelta(days=1)
    return entries


# --- orchestration -------------------------------------------------------------------
async def generate(session, start: Date, end: Date, seed: int = 42) -> dict:
    """Populate the DB for [start, end]. Pure data — no indexing, no scoring rows."""
    rng = random.Random(seed)
    stats: dict = {}

    lists = build_lists(rng)
    for lst in lists.values():
        session.add(lst)
    await session.flush()  # lists before tasks.list_id

    tasks, done_by_day = build_tasks(rng, lists)
    for t in tasks:
        session.add(t)
    await session.flush()  # parents exist before subtasks / FK targets before refs

    notes_by_day: dict[Date, list[str]] = {}
    spec_by_title = {s.title: s for s in TASKS}
    for t in tasks:
        spec = spec_by_title.get(t.title)
        if spec and spec.note and t.completed_at:
            notes_by_day.setdefault(t.completed_at.date(), []).append(spec.note)

    focus: list[FocusSession] = []
    for delta in range((end - start).days + 1):
        day = start + timedelta(days=delta)
        focus.extend(build_focus(rng, day, phase_of(day, start), done_by_day.get(day, [])))
    for f in focus:
        session.add(f)

    habits, logs, run_days = build_habits(rng, start, end)
    for h in habits:
        session.add(h)
    for log in logs:
        session.add(log)

    entries = build_journal(rng, start, end, notes_by_day, run_days)
    for e in entries:
        session.add(e)
    await session.commit()

    # Snapshot telemetry exactly as the journal API would (single source of truth).
    for e in entries:
        metrics = await collect_daily_metrics(session, e.date)
        e.hours_deep_work = metrics.deep_work_hours
        e.tasks_planned = metrics.tasks_planned
        e.tasks_done = metrics.tasks_completed
        session.add(e)
    await session.commit()

    stats.update(
        lists=len(lists),
        tasks=len(tasks),
        subtasks=sum(1 for t in tasks if t.parent_id),
        tasks_open=sum(1 for t in tasks if t.status in ("todo", "in_progress")),
        focus_sessions=len(focus),
        focus_minutes=sum(f.duration_minutes for f in focus),
        habits=len(habits),
        habit_logs=len(logs),
        journal_entries=len(entries),
    )
    return stats


async def reindex_search(session, embed: bool) -> dict:
    if not embed:
        search._embed_model = lambda: None  # FTS-only; no model download
    return await search.reindex(session)


async def target_deep_work_hours(session) -> float:
    """The user's configured target, else the scoring default (4h)."""
    rows = (await session.exec(text("SELECT value FROM app_settings WHERE key = 'target_deep_work_hours'"))).all()
    try:
        return float(rows[0][0])
    except (IndexError, TypeError, ValueError):
        return 4.0


async def weekly_preview(session, start: Date, end: Date, target: float) -> list[tuple[str, float]]:
    """Deterministic-score averages per ISO week — a sanity preview of the arc
    the daily agent will see (no LLM involved)."""
    preview: list[tuple[str, float]] = []
    week = monday_of(start)
    while week <= end:
        scores = []
        for delta in range(7):
            day = week + timedelta(days=delta)
            if day > end:
                break
            metrics = await collect_daily_metrics(session, day)
            if metrics.tasks_planned or metrics.deep_work_hours:
                scores.append(compute_daily_score(metrics, target).final_score)
        if scores:
            preview.append((week.isoformat(), sum(scores) / len(scores)))
        week += timedelta(days=7)
    return preview


def report(start: Date, end: Date, stats: dict, index_info: dict, preview: list[tuple[str, float]], target: float) -> None:
    print(f"\nSeeded {start} → {end} ({stats['journal_entries']} journal entries, {stats['tasks']} tasks)")
    print(f"  lists={stats['lists']}  subtasks={stats['subtasks']}  open={stats['tasks_open']}"
          f"  focus={stats['focus_sessions']} sessions / {stats['focus_minutes']} min"
          f"  habits={stats['habits']} / {stats['habit_logs']} logs")
    print(f"  search index: {index_info['indexed']} docs, semantic={index_info['semantic']}")
    print(f"  deterministic daily-score preview (target deep work {target}h, nudges pending AI):")
    for week, avg in preview:
        print(f"    week of {week}: avg {avg:5.1f}")
    print("  daily_scores / weekly_summaries / monthly_summaries: left empty for the AI agents")


# --- main -----------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Seed synthetic journal/tasks data for AI-feature testing")
    ap.add_argument("--db", default=os.environ.get("JOURNAL_DB_PATH", "data/journal.db"))
    ap.add_argument("--start", default=None, help="ISO date (default: Monday 5 weeks before end)")
    ap.add_argument("--end", default=None, help="ISO date (default: today)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--no-embed", action="store_true", help="skip fastembed; index FTS only")
    ap.add_argument("--no-reset", action="store_true", help="keep existing rows (merge instead of wipe)")
    return ap.parse_args()


async def main() -> None:
    args = parse_args()
    end = d(args.end) if args.end else Date.today()
    start = d(args.start) if args.start else monday_of(end - timedelta(days=34))

    db.init_engine(f"sqlite+aiosqlite:///{args.db}")
    try:
        await db.init_db()
        async with db.get_sessionmaker()() as session:
            if args.no_reset:
                print(f"Seeding into {args.db} (existing rows kept)")
            else:
                counts = await wipe_data(session)
                wiped = {k: v for k, v in counts.items() if v}
                print(f"Reset {args.db}: removed {wiped or 'nothing'}")
                print("(app_settings and ai_usage are preserved)")
            stats = await generate(session, start, end, seed=args.seed)
            index_info = await reindex_search(session, embed=not args.no_embed)
            target = await target_deep_work_hours(session)
            preview = await weekly_preview(session, start, end, target)
            report(start, end, stats, index_info, preview, target)
    finally:
        try:
            await search.shutdown_embeddings()
        finally:
            await db.dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())

"""Weekly review (docs/05 section 3): the week's numbers computed in Python, the prompt, and change validation.

The stats here are also the screen's four stat tiles, so they never depend on the model.
"""

import json
import math

import frappe
from frappe import _
from frappe.utils import flt, getdate

from lift_log import rule, trend
from lift_log.api.utils import exercise_library, program_and_definition, targets_of, user_today
from lift_log.program import is_training, main_exercises, phase_for, routine_for, week_count, week_dates
from lift_log.targets import protein_target

CHANGE_TYPES = ("weight", "nutrition", "schedule", "other")
MAX_CHANGES = 4
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

REVIEW_SCHEMA = {
	"type": "object",
	"properties": {
		"went_well": {"type": "string"},
		"to_change": {"type": "string"},
		"changes": {
			"type": "array",
			"items": {
				"type": "object",
				"properties": {
					"change_type": {"type": "string", "enum": list(CHANGE_TYPES)},
					"title": {"type": "string"},
					"why": {"type": "string"},
					"exercise": {"type": "string"},
					"delta_kg": {"type": "number"},
				},
				"required": ["change_type", "title", "why", "exercise", "delta_kg"],
				"additionalProperties": False,
			},
		},
	},
	"required": ["went_well", "to_change", "changes"],
	"additionalProperties": False,
}

PROMPT = """You are reviewing one week of a lifting and nutrition log for the person described in the data.
Be direct and specific; cite numbers from the data. No generic advice.
Sets carry rir = reps in reserve (0 = nothing left, 4 = four or more left). Older sets carry effort
instead: easy = 3+ reps left, right = 1-2 left, hard = nothing left. Sets marked warmup are
warm-ups: they are not working sets and rule_call ignores them.
food.averages_from says whether food averages use only days the person marked complete; partly
logged days understate intake. daily holds morning weigh-ins (judge weight by the 7-day averages,
not single days), sleep hours, steps and pain (0-10). Mention pain of 4 or more.
Write:
- went_well: 1-3 sentences.
- to_change: 1-3 sentences.
- changes: up to 4 concrete changes for next week. Allowed types:
  weight (exercise name exactly as in the data, delta_kg in steps of the exercise increment,
  at most one step per exercise per week), nutrition, schedule, other.
  Only propose a weight increase when reps and effort both support it; propose a decrease
  only after two hard weeks. Respect the goals (no added leg volume).
  For changes that are not weight changes, set exercise to "" and delta_kg to 0.
Reply with only JSON:
{"went_well":"...","to_change":"...","changes":[{"change_type":"weight","title":"Squat: +2.5 kg",
"why":"...","exercise":"Barbell back squat","delta_kg":2.5}]}

DATA:
"""


def _half_up(n: float) -> int:
	return int(math.floor(n + 0.5))


def goals_text(profile) -> str:
	goal = (profile and profile.goal) or "Lose fat, get stronger"
	return f"{goal.replace(', ', ' and ', 1)}; keep thighs from growing; grow forearms."


def check_week(definition: dict | None, week: int, today) -> None:
	if not definition or not 1 <= week <= week_count(definition):
		frappe.throw(_("Invalid program week: {0}").format(week))
	if week_dates(definition, week)[0] > today:
		frappe.throw(_("Week {0} hasn't started yet.").format(week))


def _sessions(user: str, until) -> list:
	names = frappe.get_all(
		"LL Workout Session",
		filters={"user": user, "session_date": ["<=", until]},
		order_by="session_date desc",
		pluck="name",
	)
	return [frappe.get_doc("LL Workout Session", n) for n in names]


def _history(sessions: list, exercise: str, upto) -> list:
	"""Rule history: sessions on or before `upto` with this exercise, newest first."""
	out = []
	for s in sessions:
		if getdate(s.session_date) > getdate(upto):
			continue
		sets = [
			{
				"kg": (r.kg or None),
				"amount": r.amount,
				"effort": r.effort or None,
				"rir": r.rir if r.rir not in (None, "") else None,
				"warmup": bool(r.is_warmup),
				"side": r.side or None,
				"set_no": r.set_no,
			}
			for r in s.sets
			if r.exercise == exercise
		]
		if sets:
			out.append({"date": str(s.session_date), "deload": s.routine_key == "home_deload", "sets": sets})
	return out


def build_stats(user: str, profile, week: int) -> dict:
	program, definition = program_and_definition(profile)
	today = user_today(profile)
	check_week(definition, week, today)
	dates = week_dates(definition, week)
	start, end = dates[0], dates[-1]
	targets = targets_of(profile)
	protein_goal = targets["protein_g"] or protein_target(profile and profile.weight_kg) or 130
	library = exercise_library()

	all_sessions = _sessions(user, end)
	in_week = {str(s.session_date): s for s in all_sessions if start <= getdate(s.session_date) <= end}

	planned_days = [d for d in dates if is_training(routine_for(definition, d))]
	done = [s for s in in_week.values() if s.status == "done" or s.sets]
	missed = [
		f"{routine_for(definition, d)['name']} ({DAY_NAMES[d.weekday()]})"
		for d in planned_days
		if d < today and str(d) not in in_week
	]

	effort = {"easy": 0, "right": 0, "hard": 0, "unrated": 0}
	rir_counts = {"0": 0, "1": 0, "2": 0, "3": 0, "4": 0, "unrated": 0}
	warmup_sets = 0
	items = []
	for s in sorted(done, key=lambda s: s.session_date):
		routine = routine_for(definition, s.session_date) or {}
		targets_by_ex = {i["exercise"]: i for i in routine.get("items") or []}
		exercises: dict[str, list] = {}
		for r in s.sets:
			exercises.setdefault(r.exercise, []).append(r)
			if r.is_warmup:
				warmup_sets += 1
				continue
			effort[r.effort or "unrated"] += 1
			rir_counts[str(r.rir) if r.rir not in (None, "") else "unrated"] += 1
		rows = []
		for name, sets in exercises.items():
			item = targets_by_ex.get(name)
			info = library.get(name, {"type": "load", "increment_kg": 2.5})
			row = {
				"name": name,
				"target": f"{item['sets']} x {item['reps']}" if item else None,
				"sets": [
					{
						"kg": r.kg or None,
						"reps": r.amount,
						"effort": r.effort or None,
						**({"rir": int(r.rir)} if r.rir not in (None, "") else {}),
						**({"warmup": True} if r.is_warmup else {}),
						**({"side": r.side} if r.side else {}),
					}
					for r in sets
				],
			}
			if item:
				call = rule.next_call(
					{"type": info["type"], "increment_kg": info["increment_kg"]},
					{
						"sets": item["sets"],
						"reps": item["reps"],
						"test": item.get("test"),
						"startingKg": (definition.get("starting_weights_kg") or {}).get(name),
					},
					_history(all_sessions, name, s.session_date),
				)
				row["rule_call"] = {k: call[k] for k in ("call", "kg") if k in call}
			rows.append(row)
		items.append(
			{
				"date": str(s.session_date),
				"routine": s.routine_name,
				"note": s.note or "",
				"main_lifts": main_exercises(routine),
				"exercises": rows,
			}
		)

	by_day = []
	for d in dates:
		name = frappe.db.get_value("LL Food Day", {"user": user, "food_date": d}, "name")
		day_doc = frappe.get_doc("LL Food Day", name) if name else None
		entries = day_doc.entries if day_doc else []
		if entries:
			by_day.append(
				{
					"date": str(d),
					"kcal": round(sum(flt(e.qty) * flt(e.kcal_per_portion) for e in entries)),
					"protein_g": round(sum(flt(e.qty) * flt(e.protein_per_portion) for e in entries)),
					"complete": bool(day_doc.complete),
				}
			)
		else:
			by_day.append({"date": str(d), "kcal": None, "protein_g": None, "complete": False})
	logged = [d for d in by_day if d["kcal"] is not None]
	complete_days = [d for d in logged if d["complete"]]
	# Partly logged days understate intake, so once any day is marked complete only those count.
	counted = complete_days or logged

	checkin = frappe.db.get_value(
		"LL Check In",
		{"user": user, "program": program, "week": week},
		["weight_kg", "waist_cm", "forearm_cm", "sleep", "energy"],
		as_dict=True,
	)
	previous = frappe.get_all(
		"LL Check In",
		filters={"user": user, "program": program, "week": ["<", week], "weight_kg": [">", 0]},
		fields=["weight_kg"],
		order_by="week desc",
		limit=1,
	)
	weight = (checkin and checkin.weight_kg) or None
	change = round(weight - previous[0].weight_kg, 1) if weight and previous else None

	previous_review = frappe.db.get_value("LL Weekly Review", {"user": user, "program": program, "week": week - 1}, "name")
	previous_changes = (
		[{"title": c.title, "accepted": bool(c.accepted)} for c in frappe.get_doc("LL Weekly Review", previous_review).changes]
		if previous_review
		else []
	)

	return {
		"week": week,
		"phase": phase_for(definition, week),
		"period": [str(start), str(end)],
		"targets": {"kcal": targets["kcal"], "protein_g": protein_goal},
		"sessions": {"planned": len(planned_days), "done": len(done), "missed": missed, "items": items},
		"effort": effort,
		"rir": rir_counts,
		"warmup_sets": warmup_sets,
		"food": {
			"days_logged": len(logged),
			"complete_days": len(complete_days),
			"averages_from": "complete days" if complete_days else "all logged days",
			"avg_kcal": _half_up(sum(d["kcal"] for d in counted) / len(counted)) if counted else None,
			"avg_protein_g": _half_up(sum(d["protein_g"] for d in counted) / len(counted)) if counted else None,
			"protein_days_hit": sum(1 for d in logged if d["protein_g"] >= protein_goal),
			"by_day": by_day,
		},
		"daily": daily_stats(user, start, end),
		"checkin": {
			"weight_kg": weight,
			"weight_change_kg": change,
			"waist_cm": (checkin and checkin.waist_cm) or None,
			"forearm_cm": (checkin and checkin.forearm_cm) or None,
			"sleep": (checkin and checkin.sleep) or None,
			"energy": (checkin and checkin.energy) or None,
		},
		"previous_review_changes": previous_changes,
		"goals": goals_text(profile),
	}


def daily_stats(user: str, start, end) -> dict:
	"""The week's daily logs: weigh-ins and the 7-day weight trend at the week's end, sleep, steps, pain."""
	from datetime import timedelta

	rows = frappe.get_all(
		"LL Daily Log",
		filters={"user": user, "log_date": ["between", [start - timedelta(days=7), end]]},
		fields=["log_date", "weight_kg", "sleep_hours", "steps", "pain", "pain_area"],
		order_by="log_date asc",
	)
	week = [r for r in rows if start <= getdate(r.log_date) <= end]

	def avg(field, places=1):
		values = [flt(r.get(field)) for r in week if flt(r.get(field))]
		return round(sum(values) / len(values), places) if values else None

	pains = [(r.log_date, int(r.pain), r.pain_area) for r in week if r.pain not in (None, "")]
	return {
		"days_logged": len(week),
		"weigh_ins": sum(1 for r in week if flt(r.weight_kg)),
		"weight_trend": trend.summary({r.log_date: flt(r.weight_kg) for r in rows if flt(r.weight_kg)}, getdate(end)),
		"avg_sleep_hours": avg("sleep_hours"),
		"avg_steps": round(avg("steps", 0)) if avg("steps", 0) is not None else None,
		"pain_days": [{"date": str(d), "pain": p, "area": a or None} for d, p, a in pains if p > 0],
		"max_pain": max((p for _d, p, _a in pains), default=None),
	}


def review_prompt(stats: dict) -> str:
	return PROMPT + json.dumps(stats, indent=1)


def clean_changes(raw, week: int) -> list[dict]:
	"""Keep at most 4 valid changes. Weight changes must name a known exercise and move exactly one
	increment, at most one per exercise."""
	library = exercise_library()
	out, weighted = [], set()
	for c in raw if isinstance(raw, list) else []:
		if not isinstance(c, dict):
			continue
		change_type = str(c.get("change_type") or "").lower()
		title = str(c.get("title") or "").strip()
		if change_type not in CHANGE_TYPES or not title:
			continue
		change = {
			"change_type": change_type,
			"title": title[:140],
			"why": str(c.get("why") or "").strip()[:300],
			"exercise": None,
			"delta_kg": 0,
			"applies_from_week": week + 1,
		}
		if change_type == "weight":
			exercise = str(c.get("exercise") or "").strip()
			info = library.get(exercise)
			try:
				delta = float(c.get("delta_kg"))
			except (TypeError, ValueError):
				continue
			inc = flt(info and info["increment_kg"])
			if not info or not inc or exercise in weighted or abs(abs(delta) - inc) > 1e-6:
				continue
			weighted.add(exercise)
			change.update(exercise=exercise, delta_kg=delta)
		out.append(change)
		if len(out) == MAX_CHANGES:
			break
	return out


def followup_prompt(stats: dict, review: dict, question: str) -> str:
	return "\n".join(
		[
			"You wrote the weekly review below for one week of a lifting and nutrition log (DATA).",
			"Answer the person's question about that week in plain text, under 120 words.",
			"Be direct and specific; cite numbers from the data. No generic advice. No markdown.",
			"",
			"DATA:",
			json.dumps(stats, indent=1),
			"",
			"REVIEW:",
			json.dumps(review, indent=1),
			"",
			f"QUESTION: {question}",
		]
	)

from datetime import timedelta

import frappe
from frappe.utils import cint, flt

from lift_log.api.utils import (
	current_user,
	get_profile,
	opt_number,
	program_and_definition,
	targets_of,
	user_today,
)
from lift_log.program import is_training, routine_for, start_date, week_count, week_dates, week_for

# Progress lifts table: label and program exercise name.
LIFTS = (
	("Back squat", "Barbell back squat"),
	("Romanian deadlift", "Barbell Romanian deadlift"),
	("Hip thrust", "Hip thrust"),
	("Bench press", "Barbell bench press"),
	("Deadlift", "Conventional deadlift"),
	("Row", "Bent-over barbell row"),
	("Overhead press", "Standing overhead press"),
)


@frappe.whitelist(methods=["GET"])
def summary(week: int | None = None) -> dict:
	user = current_user()
	profile = get_profile(user)
	program, definition = program_and_definition(profile)
	today = user_today(profile)
	empty = {
		"week": None,
		"sessions": {"done": 0, "planned_to_date": 0},
		"protein_target_g": targets_of(profile)["protein_g"],
		"protein_days_hit": 0,
		"protein_by_day": [],
		"lifts": [],
		"bodyweight": [],
		"forearm": [],
	}
	if not definition:
		return empty

	last_week = week_count(definition)
	week = cint(week) or week_for(definition, today) or (last_week if today > start_date(definition) else 1)
	week = min(max(week, 1), last_week)
	block_start, block_end = start_date(definition), week_dates(definition, last_week)[-1]

	protein_target = targets_of(profile)["protein_g"]
	protein_by_day = _protein_by_day(user, week_dates(definition, week))

	return {
		"week": week,
		"sessions": _sessions(user, definition, block_start, min(today, block_end), today),
		"protein_target_g": protein_target,
		"protein_days_hit": sum(
			1 for d in protein_by_day if protein_target and d["protein_g"] is not None and d["protein_g"] >= protein_target
		),
		"protein_by_day": protein_by_day,
		"lifts": _lifts(user, definition, block_start, block_end),
		"bodyweight": _measurements(user, program, "weight_kg", "kg"),
		"forearm": _measurements(user, program, "forearm_cm", "cm"),
	}


def _sessions(user, definition, block_start, until, today) -> dict:
	done_dates = set(
		str(d)
		for d in frappe.get_all(
			"LL Workout Session",
			filters={"user": user, "status": "done", "session_date": ["between", [block_start, until]]},
			pluck="session_date",
		)
	)
	planned = 0
	day = block_start
	while day <= until:
		# Today only counts as planned once it's been trained.
		if is_training(routine_for(definition, day)) and (day < today or str(day) in done_dates):
			planned += 1
		day += timedelta(days=1)
	return {"done": len(done_dates), "planned_to_date": planned}


def _protein_by_day(user, days) -> list[dict]:
	totals = {
		str(r.food_date): r.protein
		for r in frappe.db.sql(
			"""
			select d.food_date, sum(e.qty * e.protein_per_portion) as protein
			from `tabLL Food Day` d
			join `tabLL Food Entry` e on e.parent = d.name and e.parenttype = 'LL Food Day'
			where d.user = %(user)s and d.food_date between %(start)s and %(end)s
			group by d.food_date
			""",
			{"user": user, "start": days[0], "end": days[-1]},
			as_dict=True,
		)
	}
	return [
		{"date": str(d), "protein_g": round(flt(totals[str(d)])) if str(d) in totals else None} for d in days
	]


def _lifts(user, definition, block_start, block_end) -> list[dict]:
	exercises = [name for _label, name in LIFTS]
	rows = frappe.db.sql(
		"""
		select e.exercise, e.kg, e.amount, s.session_date
		from `tabLL Set Entry` e
		join `tabLL Workout Session` s on e.parent = s.name and e.parenttype = 'LL Workout Session'
		where s.user = %(user)s and s.session_date between %(start)s and %(end)s
			and e.exercise in %(exercises)s and e.kg > 0
		order by s.session_date, e.idx
		""",
		{"user": user, "start": block_start, "end": block_end, "exercises": exercises},
		as_dict=True,
	)
	starting = definition.get("starting_weights_kg") or {}
	out = []
	for label, exercise in LIFTS:
		sets = [r for r in rows if r.exercise == exercise]
		if sets:
			first_day = sets[0].session_date
			start_kg = max(r.kg for r in sets if r.session_date == first_day)
			best = max(sets, key=lambda r: (r.kg, r.amount))
			best = {"kg": best.kg, "amount": best.amount, "date": str(best.session_date)}
		else:
			start_kg, best = starting.get(exercise), None
		out.append({"label": label, "exercise": exercise, "start_kg": start_kg, "best": best})
	return out


def _measurements(user, program, field, unit) -> list[dict]:
	rows = frappe.get_all(
		"LL Check In",
		filters={"user": user, "program": program},
		fields=["week", field],
		order_by="week asc",
	)
	return [{"week": r.week, unit: opt_number(r.get(field))} for r in rows]

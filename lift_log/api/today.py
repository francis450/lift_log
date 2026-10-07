import frappe

from lift_log.api.utils import (
	current_user,
	day_totals,
	food_day_name,
	get_profile,
	opt_number,
	parse_date,
	program_and_definition,
	session_dict,
	session_name,
	targets_of,
	user_today,
)
from lift_log.program import calendar_week, main_exercises, phase_for, routine_for, week_for


@frappe.whitelist(methods=["GET"])
def get(date: str | None = None) -> dict:
	user = current_user()
	profile = get_profile(user)
	day = parse_date(date) if date else user_today(profile)
	_program, definition = program_and_definition(profile)

	week = week_for(definition, day) if definition else None
	routine = routine_for(definition, day) if definition else None
	name = session_name(user, day)
	food_name = food_day_name(user, day)

	return {
		"date": str(day),
		"week": week,
		"phase": phase_for(definition, week) if definition else None,
		"routine": routine,
		"session": session_dict(frappe.get_doc("LL Workout Session", name)) if name else None,
		"food": day_totals(frappe.get_doc("LL Food Day", food_name).entries if food_name else []),
		"targets": targets_of(profile),
		"targets_note": (profile and profile.targets_note) or None,
		"week_strip": week_strip(user, day),
		"last_session": last_session(user, day, definition),
	}


def week_strip(user: str, day) -> list[dict]:
	days = calendar_week(day)
	trained = {
		str(r.session_date)
		for r in frappe.db.sql(
			"""
			select s.session_date, s.status, count(e.name) as sets
			from `tabLL Workout Session` s
			left join `tabLL Set Entry` e on e.parent = s.name and e.parenttype = 'LL Workout Session'
			where s.user = %(user)s and s.session_date between %(start)s and %(end)s
			group by s.name, s.session_date, s.status
			""",
			{"user": user, "start": days[0], "end": days[-1]},
			as_dict=True,
		)
		if r.status == "done" or r.sets
	}
	fed = {
		str(r.food_date)
		for r in frappe.db.sql(
			"""
			select d.food_date
			from `tabLL Food Day` d
			join `tabLL Food Entry` e on e.parent = d.name and e.parenttype = 'LL Food Day'
			where d.user = %(user)s and d.food_date between %(start)s and %(end)s
			group by d.name, d.food_date
			""",
			{"user": user, "start": days[0], "end": days[-1]},
			as_dict=True,
		)
	}
	return [{"date": str(d), "trained": str(d) in trained, "fed": str(d) in fed} for d in days]


def last_session(user: str, day, definition: dict | None) -> dict | None:
	"""The most recent finished session up to the date, with its key lift."""
	names = frappe.get_all(
		"LL Workout Session",
		filters={"user": user, "status": "done", "session_date": ["<=", day]},
		order_by="session_date desc",
		pluck="name",
		limit=1,
	)
	if not names:
		return None
	doc = frappe.get_doc("LL Workout Session", names[0])
	routine = routine_for(definition, doc.session_date) if definition else None
	return {
		"date": str(doc.session_date),
		"routine_name": doc.routine_name,
		"highlight": key_lift(doc, main_exercises(routine)),
	}


def key_lift(doc, mains: list[str]) -> dict | None:
	"""The routine's main lift if logged, else the first weighted exercise, else the first exercise."""
	by_exercise: dict[str, list] = {}
	for row in doc.sets:
		by_exercise.setdefault(row.exercise, []).append(row)
	if not by_exercise:
		return None
	pick = next((ex for ex in by_exercise if ex in mains), None)
	pick = pick or next((ex for ex, rows in by_exercise.items() if any(r.kg for r in rows)), None)
	pick = pick or next(iter(by_exercise))
	return {
		"exercise": pick,
		"sets": [{"kg": opt_number(r.kg), "amount": r.amount} for r in by_exercise[pick]],
	}

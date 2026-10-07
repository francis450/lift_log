import calendar

import frappe
from frappe import _
from frappe.utils import cint, flt

from lift_log.api.utils import (
	as_list,
	conflict,
	current_user,
	get_profile,
	is_stale,
	now_utc,
	opt_number,
	parse_date,
	parse_utc,
	program_and_definition,
	session_dict,
	session_name,
)
from lift_log.program import week_for

EFFORTS = ("", "easy", "right", "hard")
STATUSES = ("in_progress", "done")


@frappe.whitelist(methods=["GET"])
def get(date: str) -> dict | None:
	user = current_user()
	name = session_name(user, parse_date(date))
	return session_dict(frappe.get_doc("LL Workout Session", name)) if name else None


@frappe.whitelist(methods=["POST"])
def save(
	session_date: str,
	client_updated_at: str | None = None,
	sets=None,
	week: int | None = None,
	routine_key: str | None = None,
	routine_name: str | None = None,
	status: str | None = None,
	started_at: str | None = None,
	finished_at: str | None = None,
	note: str | None = None,
) -> dict:
	"""Upsert by (user, session_date), replacing the sets with what the client sends.
	A write older than the stored one gets HTTP 409 and the stored session."""
	user = current_user()
	day = parse_date(session_date, "session_date")
	incoming_at = parse_utc(client_updated_at) or now_utc()
	status = status or "in_progress"
	if status not in STATUSES:
		frappe.throw(_("Invalid status: {0}").format(status))

	name = frappe.db.get_value("LL Workout Session", {"user": user, "session_date": day}, "name", for_update=True)
	if name:
		doc = frappe.get_doc("LL Workout Session", name)
		if is_stale(doc.client_updated_at, incoming_at):
			return conflict(session_dict(doc))
	else:
		doc = frappe.new_doc("LL Workout Session")
		doc.user = user
		doc.session_date = day

	program, definition = program_and_definition(get_profile(user))
	doc.program = doc.program or program
	doc.update(
		{
			"week": (week_for(definition, day) if definition else None) or cint(week),
			"routine_key": routine_key,
			"routine_name": routine_name,
			"status": status,
			"started_at": parse_utc(started_at),
			"finished_at": parse_utc(finished_at),
			"note": note or "",
			"client_updated_at": incoming_at,
		}
	)
	doc.set("sets", _clean_sets(as_list(sets)))
	doc.save()
	return session_dict(doc)


def _clean_sets(sets: list) -> list[dict]:
	"""Rows with no reps entered are not saved."""
	rows, per_exercise = [], {}
	for s in sets:
		exercise = (s.get("exercise") or "").strip()
		if not exercise:
			frappe.throw(_("Every set needs an exercise."))
		if s.get("amount") in (None, ""):
			continue
		effort = (s.get("effort") or "").lower()
		if effort not in EFFORTS:
			frappe.throw(_("Invalid effort: {0}").format(effort))
		per_exercise[exercise] = per_exercise.get(exercise, 0) + 1
		rows.append(
			{
				"exercise": exercise,
				"set_no": cint(s.get("set_no")) or per_exercise[exercise],
				"kg": flt(s.get("kg")) if s.get("kg") not in (None, "") else 0,
				"amount": flt(s.get("amount")),
				"effort": effort,
				"done": 1 if s.get("done") in (True, 1, "1", "true") else 0,
			}
		)
	return rows


@frappe.whitelist(methods=["GET"])
def history(exercise: str, limit: int = 6) -> list[dict]:
	"""The last N sessions containing an exercise, newest first, each with only that exercise's sets."""
	user = current_user()
	limit = min(max(cint(limit) or 6, 1), 50)
	sessions = frappe.db.sql(
		"""
		select s.name, s.session_date, s.week, s.routine_key, s.routine_name, s.status
		from `tabLL Workout Session` s
		where s.user = %(user)s
			and exists (
				select 1 from `tabLL Set Entry` e
				where e.parent = s.name and e.parenttype = 'LL Workout Session' and e.exercise = %(exercise)s
			)
		order by s.session_date desc
		limit %(limit)s
		""",
		{"user": user, "exercise": exercise, "limit": limit},
		as_dict=True,
	)
	if not sessions:
		return []
	sets = frappe.db.sql(
		"""
		select parent, set_no, kg, amount, effort, done
		from `tabLL Set Entry`
		where parenttype = 'LL Workout Session' and exercise = %(exercise)s and parent in %(parents)s
		order by idx
		""",
		{"exercise": exercise, "parents": [s.name for s in sessions]},
		as_dict=True,
	)
	by_parent: dict[str, list] = {}
	for row in sets:
		by_parent.setdefault(row.parent, []).append(
			{
				"set_no": row.set_no,
				"kg": opt_number(row.kg),
				"amount": row.amount,
				"effort": row.effort or None,
				"done": bool(row.done),
			}
		)
	return [
		{
			"date": str(s.session_date),
			"week": s.week or None,
			"routine_key": s.routine_key,
			"routine_name": s.routine_name,
			"status": s.status,
			"exercise": exercise,
			"sets": by_parent.get(s.name, []),
		}
		for s in sessions
	]


@frappe.whitelist(methods=["GET"])
def month(month: str) -> list[dict]:
	"""Sessions in a calendar month (YYYY-MM) for the History calendar."""
	user = current_user()
	try:
		year, mon = (int(part) for part in month.split("-"))
		first = parse_date(f"{year:04d}-{mon:02d}-01")
	except (ValueError, AttributeError):
		frappe.throw(_("Invalid month: {0}. Use YYYY-MM.").format(month))
	last = first.replace(day=calendar.monthrange(year, mon)[1])
	rows = frappe.db.sql(
		"""
		select s.session_date, s.routine_key, s.routine_name, s.status, count(e.name) as sets
		from `tabLL Workout Session` s
		left join `tabLL Set Entry` e on e.parent = s.name and e.parenttype = 'LL Workout Session'
		where s.user = %(user)s and s.session_date between %(first)s and %(last)s
		group by s.name, s.session_date, s.routine_key, s.routine_name, s.status
		order by s.session_date
		""",
		{"user": user, "first": first, "last": last},
		as_dict=True,
	)
	return [
		{
			"date": str(r.session_date),
			"routine_key": r.routine_key,
			"routine_name": r.routine_name,
			"sets": r.sets,
			"status": r.status,
		}
		for r in rows
	]

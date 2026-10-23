"""AI endpoints (docs/05): estimates, suggestions and the weekly review."""

import base64
import binascii
import json
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import cint, flt

from lift_log.ai import prompts, review
from lift_log.ai.client import AIError, check_allowed, clean_items, complete, complete_json, settings
from lift_log.api.utils import (
	current_user,
	day_totals,
	food_day_name,
	format_time,
	get_profile,
	now_utc,
	parse_date,
	program_and_definition,
	review_dict,
	targets_of,
	user_today,
)
from lift_log.program import is_training, routine_for
from lift_log.targets import protein_target

QUICK_TIMEOUT = 30
IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp", "image/gif")
MEALS = ("breakfast", "lunch", "dinner", "snacks")
USUAL_FALLBACK = "chapati, rice, beef stew, chicken, lentils, beans, eggs"


@frappe.whitelist(methods=["POST"])
def estimate(text: str | None = None, image_base64: str | None = None, image_mime: str | None = None) -> dict:
	"""Split a meal (photo and/or description) into foods with portion, kcal and protein."""
	user = current_user()
	profile = get_profile(user)
	text = (text or "").strip()
	if not text and not image_base64:
		frappe.throw(_("Add a photo or describe what you ate."))

	s = settings()
	content: list | str
	if image_base64:
		mime = (image_mime or "image/jpeg").lower()
		if mime not in IMAGE_TYPES:
			frappe.throw(_("Use a JPEG, PNG, WebP or GIF photo."))
		try:
			size = len(base64.b64decode(image_base64, validate=True))
		except (binascii.Error, ValueError):
			frappe.throw(_("That photo couldn't be read. Take it again."))
		if size > flt(s.max_image_mb or 5) * 1024 * 1024:
			frappe.throw(_("That photo is too large. Take it again."))
		model = s.model_vision
		feature = "estimate_photo"
		content = [
			{"type": "image", "source": {"type": "base64", "media_type": mime, "data": image_base64}},
			{"type": "text", "text": prompts.estimate_prompt(text, has_image=True)},
		]
	else:
		model = s.model_quick
		feature = "estimate_text"
		content = prompts.estimate_prompt(text, has_image=False)

	check_allowed(user, profile)
	data = complete_json(
		user=user,
		feature=feature,
		model=model,
		content=content,
		timeout=QUICK_TIMEOUT,
		schema=prompts.ESTIMATE_SCHEMA,
		effort="low",
	)
	return {"items": clean_items(data), "model": model}


# Each main meal's share of the day. What's left is split over the meals still to come, so lunch
# leaves room for dinner. Snacks get a small slice while dinner is still to come.
MEAL_SHARES = {"breakfast": 25, "lunch": 35, "dinner": 40}
SNACK_SHARE = 0.10
# Options more than this far over the meal's budget are dropped (unless every option is).
OVER_BUDGET = 1.2
EXCLUDE_LIMIT = 12


def meal_budget(
	meal: str | None, kcal_left: float, protein_left: float, kcal: float, protein: float, logged: set[str]
) -> dict:
	"""The part of what's left for this meal, and what it leaves for the meals still to come."""
	order = list(MEAL_SHARES)
	if meal in MEAL_SHARES:
		later = [m for m in order[order.index(meal) + 1 :] if m not in logged]
		share = MEAL_SHARES[meal] / (MEAL_SHARES[meal] + sum(MEAL_SHARES[m] for m in later))
		meal_kcal, meal_protein = kcal_left * share, protein_left * share
	elif meal == "snacks" and "dinner" not in logged:
		later = ["dinner"]
		meal_kcal, meal_protein = min(kcal_left, kcal * SNACK_SHARE), min(protein_left, protein * SNACK_SHARE)
	else:
		later = []
		meal_kcal, meal_protein = kcal_left, protein_left
	return {
		"kcal": round(meal_kcal),
		"protein_g": round(meal_protein),
		"later": " and ".join(later),
		"later_kcal": round(kcal_left - meal_kcal),
		"later_protein_g": round(protein_left - meal_protein),
	}


def _titles(exclude) -> list[str]:
	if isinstance(exclude, str):
		try:
			exclude = json.loads(exclude)
		except ValueError:
			exclude = [exclude]
	if not isinstance(exclude, list):
		return []
	titles = [str(t).strip()[:140] for t in exclude if str(t or "").strip()]
	return titles[-EXCLUDE_LIMIT:]


@frappe.whitelist(methods=["POST"])
def suggest(date: str | None = None, meal: str | None = None, exclude: str | list | None = None) -> dict:
	"""Up to 4 meal options sized to this meal's share of what's left, leaving room for later meals."""
	user = current_user()
	profile = get_profile(user)
	check_allowed(user, profile)
	day = parse_date(date) if date else user_today(profile)
	meal = (meal or "").lower() or None
	if meal and meal not in MEALS:
		frappe.throw(_("Invalid meal: {0}").format(meal))

	ctx = suggest_context(user, profile, day, meal)
	ctx["exclude"] = _titles(exclude)
	s = settings()
	data = complete_json(
		user=user,
		feature="suggest",
		model=s.model_quick,
		content=prompts.suggest_prompt(ctx),
		timeout=QUICK_TIMEOUT,
		schema=prompts.SUGGEST_SCHEMA,
		effort="low",
	)
	options = []
	for option in (data.get("options") if isinstance(data, dict) else data) or []:
		if not isinstance(option, dict):
			continue
		items = clean_items(option.get("items"))
		if items and str(option.get("title") or "").strip():
			options.append(
				{"title": str(option["title"]).strip()[:140], "why": str(option.get("why") or "").strip()[:300], "items": items}
			)
	budget = ctx["budget"]
	within = [o for o in options if sum(i["kcal"] for i in o["items"]) <= budget["kcal"] * OVER_BUDGET]
	options = (within or options)[:4]
	if not options:
		frappe.throw(_("Couldn't come up with a suggestion. Try again."), AIError)
	return {
		"options": options,
		"budget": {"kcal": budget["kcal"], "protein_g": budget["protein_g"]},
		"model": s.model_quick,
	}


def suggest_context(user: str, profile, day, meal: str | None) -> dict:
	"""Everything the suggestion prompt needs, built on the server (docs/05)."""
	name = food_day_name(user, day)
	entries = frappe.get_doc("LL Food Day", name).entries if name else []
	eaten_totals = day_totals(entries)
	by_meal: dict[str, list[str]] = {}
	for e in entries:
		qty = int(e.qty) if float(e.qty).is_integer() else e.qty
		by_meal.setdefault(e.meal, []).append(f"{e.food_name} x {qty}")
	eaten = "; ".join(f"{m}: {', '.join(foods)}" for m, foods in by_meal.items()) or "nothing yet"

	targets = targets_of(profile)
	kcal = targets["kcal"]
	protein = targets["protein_g"] or protein_target(profile and profile.weight_kg) or 130

	_program, definition = program_and_definition(profile)
	routine = routine_for(definition, day) if definition else None
	if is_training(routine):
		training = f"{routine['name']} at {format_time(profile and profile.session_time) or '18:00'}"
	else:
		training = "rest day"

	usual = frappe.db.sql(
		"""
		select e.food_name, count(*) as n
		from `tabLL Food Entry` e
		join `tabLL Food Day` d on e.parent = d.name and e.parenttype = 'LL Food Day'
		where d.user = %(user)s and d.food_date >= %(since)s
		group by e.food_name
		order by n desc, e.food_name
		limit 15
		""",
		{"user": user, "since": day - timedelta(days=30)},
		as_dict=True,
	)
	days = len([d for d in ((profile and profile.training_days) or "mon,tue,wed,thu,fri").split(",") if d])
	kcal_left = max(kcal - eaten_totals["kcal"], 0)
	protein_left = max(protein - eaten_totals["protein_g"], 0)
	return {
		"weight": f"{flt(profile and profile.weight_kg) or 72:g}",
		"days": days,
		"goal": ((profile and profile.goal) or "Lose fat, get stronger").lower(),
		"meal": meal,
		"kcal": kcal,
		"protein": protein,
		"kcal_left": kcal_left,
		"protein_left": protein_left,
		"budget": meal_budget(meal, kcal_left, protein_left, kcal, protein, set(by_meal)),
		"eaten": eaten,
		"training": training,
		"usual": ", ".join(r.food_name for r in usual) or USUAL_FALLBACK,
	}


REVIEW_TIMEOUT = 90


def _review_doc(user: str, program: str, week: int):
	name = frappe.db.get_value("LL Weekly Review", {"user": user, "program": program, "week": week}, "name")
	return frappe.get_doc("LL Weekly Review", name) if name else None


@frappe.whitelist(methods=["GET"])
def review_stats(week: int) -> dict:
	"""The week's numbers without Claude: the app shows the four stat tiles from these while the review runs."""
	user = current_user()
	return review.build_stats(user, get_profile(user), cint(week))


@frappe.whitelist(methods=["POST"])
def weekly_review(week: int, regenerate: bool = False) -> dict:
	"""The stored review for the week, or a new one from Claude (one per user per week; regenerate replaces it)."""
	user = current_user()
	profile = get_profile(user)
	week = cint(week)
	program, _definition = program_and_definition(profile)
	doc = _review_doc(user, program, week)
	if doc and not cint(regenerate) and doc.generated_at:
		return review_dict(doc)

	stats = review.build_stats(user, profile, week)
	check_allowed(user, profile)
	model = settings().model_review
	data = complete_json(
		user=user,
		feature="review",
		model=model,
		content=review.review_prompt(stats),
		timeout=REVIEW_TIMEOUT,
		schema=review.REVIEW_SCHEMA,
		effort="medium",
		max_tokens=16000,
	)
	if not isinstance(data, dict):
		frappe.throw(_("Couldn't read the review. Try again."), AIError)

	doc = doc or frappe.new_doc("LL Weekly Review")
	doc.update(
		{
			"user": user,
			"program": program,
			"week": week,
			"period_start": stats["period"][0],
			"period_end": stats["period"][1],
			"stats": json.dumps(stats),
			"went_well": str(data.get("went_well") or "").strip(),
			"to_change": str(data.get("to_change") or "").strip(),
			"model": model,
			"generated_at": now_utc(),
		}
	)
	doc.set("changes", review.clean_changes(data.get("changes"), week))
	doc.save()
	return review_dict(doc)


@frappe.whitelist(methods=["POST"])
def review_followup(week: int, question: str) -> dict:
	"""One question about the week, answered in plain text (under 120 words). Not stored."""
	user = current_user()
	profile = get_profile(user)
	question = (question or "").strip()[:500]
	if not question:
		frappe.throw(_("Type a question."))
	program, _definition = program_and_definition(profile)
	doc = _review_doc(user, program, cint(week))
	if not doc or not doc.generated_at:
		frappe.throw(_("Open the weekly review first."))
	check_allowed(user, profile)
	stored = review_dict(doc)
	answer = complete(
		user=user,
		feature="review_followup",
		model=settings().model_review,
		content=review.followup_prompt(stored["stats"], {k: stored[k] for k in ("went_well", "to_change", "changes")}, question),
		timeout=REVIEW_TIMEOUT,
		effort="low",
		max_tokens=4000,
	)
	if not answer:
		frappe.throw(_("Claude didn't answer. Try again."), AIError)
	return {"answer": answer}


@frappe.whitelist(methods=["POST"])
def apply_changes(week: int, accepted=None) -> dict:
	"""Mark the accepted changes (indexes into the review's changes); the rest are left unaccepted."""
	user = current_user()
	program, _definition = program_and_definition(get_profile(user))
	doc = _review_doc(user, program, cint(week))
	if not doc:
		frappe.throw(_("There's no review for week {0} yet.").format(week))
	if isinstance(accepted, str):
		accepted = json.loads(accepted or "[]")
	chosen = {cint(i) for i in accepted or []}
	for i, change in enumerate(doc.changes):
		change.accepted = 1 if i in chosen else 0
	doc.save()
	return review_dict(doc)


@frappe.whitelist(methods=["GET"])
def plan_changes(week: int) -> list[dict]:
	"""Accepted changes that apply to this week. The app adds weight changes' delta_kg to its suggestions."""
	user = current_user()
	program, _definition = program_and_definition(get_profile(user))
	rows = frappe.db.sql(
		"""
		select c.change_type, c.title, c.why, c.exercise, c.delta_kg
		from `tabLL Plan Change` c
		join `tabLL Weekly Review` r on c.parent = r.name and c.parenttype = 'LL Weekly Review'
		where r.user = %(user)s and r.program = %(program)s and c.accepted = 1 and c.applies_from_week = %(week)s
		order by r.week, c.idx
		""",
		{"user": user, "program": program, "week": cint(week)},
		as_dict=True,
	)
	return [
		{
			"change_type": r.change_type,
			"title": r.title,
			"why": r.why or "",
			"exercise": r.exercise,
			"delta_kg": r.delta_kg or None,
		}
		for r in rows
	]

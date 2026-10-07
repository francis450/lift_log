import frappe

from lift_log.api.utils import (
	checkin_dict,
	current_user,
	food_day_dict,
	food_item_dict,
	get_profile,
	iso_utc,
	now_utc,
	profile_dict,
	review_dict,
	session_dict,
)


def _docs(doctype: str, user: str, order_by: str) -> list:
	return [
		frappe.get_doc(doctype, name)
		for name in frappe.get_all(doctype, filters={"user": user}, order_by=order_by, pluck="name")
	]


@frappe.whitelist(methods=["GET"])
def all() -> dict:
	"""Everything the user owns as one JSON document. Check-in photos are URLs, not files."""
	user = current_user()
	profile = get_profile(user)
	custom_foods = frappe.get_all(
		"LL Food Item",
		filters={"is_seed": 0, "user": user},
		fields=["name", "food_name", "portion", "kcal", "protein_g"],
		order_by="food_name asc",
	)
	return {
		"exported_at": iso_utc(now_utc()),
		"user": user,
		"profile": profile_dict(profile, with_program=False) if profile else None,
		"sessions": [session_dict(d) for d in _docs("LL Workout Session", user, "session_date asc")],
		"food_days": [food_day_dict(d) for d in _docs("LL Food Day", user, "food_date asc")],
		"custom_foods": [food_item_dict(i) for i in custom_foods],
		"checkins": [checkin_dict(d) for d in _docs("LL Check In", user, "checkin_date asc")],
		"reviews": [review_dict(d) for d in _docs("LL Weekly Review", user, "week asc")],
	}

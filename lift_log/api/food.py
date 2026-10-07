from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import cint, flt

from lift_log.api.utils import (
	as_list,
	conflict,
	current_user,
	food_day_dict,
	food_day_name,
	food_item_dict,
	get_profile,
	is_stale,
	now_utc,
	parse_date,
	parse_utc,
	user_today,
)

MEALS = ("breakfast", "lunch", "dinner", "snacks")
SOURCES = ("search", "custom", "describe", "photo", "suggestion", "migrated")


@frappe.whitelist(methods=["GET"])
def get_day(date: str) -> dict:
	user = current_user()
	day = parse_date(date)
	name = food_day_name(user, day)
	if not name:
		return {"food_date": str(day), "client_updated_at": None, "entries": []}
	return food_day_dict(frappe.get_doc("LL Food Day", name))


@frappe.whitelist(methods=["POST"])
def save_day(food_date: str, client_updated_at: str | None = None, entries=None) -> dict:
	"""Upsert by (user, food_date), replacing the entries. Entries sharing a client_id collapse to one.
	A write older than the stored one gets HTTP 409 and the stored day."""
	user = current_user()
	day = parse_date(food_date, "food_date")
	incoming_at = parse_utc(client_updated_at) or now_utc()

	name = frappe.db.get_value("LL Food Day", {"user": user, "food_date": day}, "name", for_update=True)
	if name:
		doc = frappe.get_doc("LL Food Day", name)
		if is_stale(doc.client_updated_at, incoming_at):
			return conflict(food_day_dict(doc))
	else:
		doc = frappe.new_doc("LL Food Day")
		doc.user = user
		doc.food_date = day

	doc.client_updated_at = incoming_at
	doc.set("entries", [_clean_entry(e, incoming_at) for e in as_list(entries)])
	doc.save()
	return food_day_dict(doc)


def _clean_entry(entry: dict, default_added_at) -> dict:
	client_id = str(entry.get("client_id") or "").strip()
	food_name = (entry.get("food_name") or "").strip()
	meal = (entry.get("meal") or "").strip().lower()
	source = (entry.get("source") or "search").strip().lower()
	if not client_id:
		frappe.throw(_("Every food entry needs a client_id."))
	if not food_name:
		frappe.throw(_("Every food entry needs a name."))
	if meal not in MEALS:
		frappe.throw(_("Invalid meal: {0}").format(entry.get("meal")))
	if source not in SOURCES:
		frappe.throw(_("Invalid source: {0}").format(entry.get("source")))
	qty = entry.get("qty")
	return {
		"client_id": client_id,
		"meal": meal,
		"food_name": food_name,
		"portion": entry.get("portion") or "",
		"qty": 1 if qty in (None, "") else flt(qty),
		"kcal_per_portion": flt(entry.get("kcal_per_portion")),
		"protein_per_portion": flt(entry.get("protein_per_portion")),
		"source": source,
		"added_at": parse_utc(entry.get("added_at")) or default_added_at,
	}


def _like(q: str) -> str:
	escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
	return f"%{escaped}%"


def _rank(items: list[dict], q: str) -> list[dict]:
	"""Names starting with the query first, then the rest; stable within each group."""
	q = q.lower()
	return sorted(items, key=lambda item: not (item["food_name"] or "").lower().startswith(q))


@frappe.whitelist(methods=["GET"])
def search(q: str = "", limit: int = 20) -> dict:
	"""The user's recent foods (last 30 days), their saved custom foods, then the seed library."""
	user = current_user()
	q = (q or "").strip()
	limit = min(max(cint(limit) or 20, 1), 100)
	pattern = _like(q)
	since = user_today(get_profile(user)) - timedelta(days=30)

	recent, seen = [], set()
	for row in frappe.db.sql(
		"""
		select e.food_name, e.portion, e.kcal_per_portion, e.protein_per_portion
		from `tabLL Food Entry` e
		join `tabLL Food Day` d on e.parent = d.name and e.parenttype = 'LL Food Day'
		where d.user = %(user)s and d.food_date >= %(since)s and e.food_name like %(pattern)s
		order by d.food_date desc, e.added_at desc, e.idx desc
		""",
		{"user": user, "since": since, "pattern": pattern},
		as_dict=True,
	):
		key = ((row.food_name or "").lower(), (row.portion or "").lower())
		if key in seen:
			continue
		seen.add(key)
		recent.append(
			{
				"name": None,
				"food_name": row.food_name,
				"portion": row.portion or "",
				"kcal": row.kcal_per_portion,
				"protein_g": row.protein_per_portion,
			}
		)

	fields = ["name", "food_name", "portion", "kcal", "protein_g"]
	mine = frappe.get_all(
		"LL Food Item",
		filters={"is_seed": 0, "user": user, "food_name": ["like", pattern]},
		fields=fields,
		order_by="food_name asc",
	)
	library = frappe.get_all(
		"LL Food Item",
		filters={"is_seed": 1, "food_name": ["like", pattern]},
		fields=fields,
		order_by="food_name asc",
	)
	return {
		"recent": _rank(recent, q)[:limit],
		"mine": _rank([food_item_dict(i) for i in mine], q)[:limit],
		"library": _rank([food_item_dict(i) for i in library], q)[:limit],
	}


@frappe.whitelist(methods=["POST"])
def save_item(food_name: str, portion: str | None = None, kcal=None, protein_g=None) -> dict:
	"""Create or update the user's custom food with this name."""
	user = current_user()
	food_name = (food_name or "").strip()
	if not food_name:
		frappe.throw(_("Enter a food name."))
	if flt(kcal) < 0 or flt(protein_g) < 0:
		frappe.throw(_("kcal and protein can't be negative."))

	name = frappe.db.get_value("LL Food Item", {"is_seed": 0, "user": user, "food_name": food_name}, "name")
	doc = frappe.get_doc("LL Food Item", name) if name else frappe.new_doc("LL Food Item")
	doc.update(
		{
			"food_name": food_name,
			"portion": portion or "",
			"kcal": flt(kcal),
			"protein_g": flt(protein_g),
			"is_seed": 0,
			"user": user,
		}
	)
	doc.save()
	return food_item_dict(doc)

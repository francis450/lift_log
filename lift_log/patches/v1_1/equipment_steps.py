"""Gym equipment as checked on 21 Nov 2026: the smallest barbell plate is 2.5 kg, so a barbell moves in
5 kg steps (2.5 kg a side). The assisted pull-up is a counterweight machine logged as help in kg; its
step is 0 until it's checked at the gym. Idempotent."""

import frappe

BARBELL_STEP_KG = 5


def execute():
	for name in frappe.get_all("LL Exercise", filters={"equipment": "barbell"}, pluck="name"):
		frappe.db.set_value("LL Exercise", name, "increment_kg", BARBELL_STEP_KG, update_modified=False)
	if frappe.db.exists("LL Exercise", "Assisted pull-up"):
		frappe.db.set_value(
			"LL Exercise",
			"Assisted pull-up",
			{"exercise_type": "assisted", "increment_kg": 0},
			update_modified=False,
		)

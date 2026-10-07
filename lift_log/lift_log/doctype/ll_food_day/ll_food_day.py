import frappe
from frappe import _
from frappe.model.document import Document

from lift_log.permissions import enforce_record_user


class LLFoodDay(Document):
	def validate(self):
		enforce_record_user(self)
		self.dedupe_entries()
		for row in self.entries:
			if (row.qty or 0) <= 0:
				frappe.throw(_("{0}: quantity must be more than 0.").format(row.food_name))
			if (row.kcal_per_portion or 0) < 0 or (row.protein_per_portion or 0) < 0:
				frappe.throw(_("{0}: kcal and protein can't be negative.").format(row.food_name))

	def dedupe_entries(self):
		"""Entries with the same client_id collapse to one: first position, latest values."""
		latest = {row.client_id: row for row in self.entries}
		if len(latest) == len(self.entries):
			return
		kept, seen = [], set()
		for row in self.entries:
			if row.client_id not in seen:
				seen.add(row.client_id)
				kept.append(latest[row.client_id])
		self.set("entries", [])
		for row in kept:
			self.append("entries", row)


def on_doctype_update():
	frappe.db.add_unique("LL Food Day", ["user", "food_date"], constraint_name="unique_user_date")

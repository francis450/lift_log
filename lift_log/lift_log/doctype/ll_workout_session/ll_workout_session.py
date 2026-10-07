import frappe
from frappe import _
from frappe.model.document import Document

from lift_log.permissions import enforce_record_user


class LLWorkoutSession(Document):
	def validate(self):
		enforce_record_user(self)
		for row in self.sets:
			if (row.kg or 0) < 0 or (row.amount or 0) < 0:
				frappe.throw(_("Row {0}: weight and reps can't be negative.").format(row.idx))


def on_doctype_update():
	frappe.db.add_unique("LL Workout Session", ["user", "session_date"], constraint_name="unique_user_date")

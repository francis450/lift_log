import frappe
from frappe.model.document import Document

from lift_log.permissions import enforce_record_user


class LLWeeklyReview(Document):
	def validate(self):
		enforce_record_user(self)


def on_doctype_update():
	frappe.db.add_unique("LL Weekly Review", ["user", "program", "week"], constraint_name="unique_user_program_week")

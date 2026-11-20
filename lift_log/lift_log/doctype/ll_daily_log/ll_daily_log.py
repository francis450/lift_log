import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from lift_log.permissions import enforce_record_user

LIMITS = {"weight_kg": (20, 300), "sleep_hours": (0, 24), "steps": (0, 100000)}


class LLDailyLog(Document):
	"""One row per user per day: morning weight, sleep, steps and pain."""

	def validate(self):
		enforce_record_user(self)
		for field, (low, high) in LIMITS.items():
			value = self.get(field)
			if value and not low <= value <= high:
				frappe.throw(_("{0} must be from {1} to {2}.").format(self.meta.get_label(field), low, high))
		if self.pain not in (None, "") and not 0 <= cint(self.pain) <= 10:
			frappe.throw(_("Pain must be from 0 to 10."))


def on_doctype_update():
	frappe.db.add_unique("LL Daily Log", ["user", "log_date"], constraint_name="unique_user_log_date")

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from lift_log.permissions import enforce_record_user


class LLCheckIn(Document):
	def validate(self):
		enforce_record_user(self)
		for field in ("sleep", "energy"):
			if self.get(field) and not 1 <= self.get(field) <= 5:
				frappe.throw(_("{0} must be from 1 to 5.").format(self.meta.get_label(field)))
		for field in ("weight_kg", "waist_cm", "forearm_cm"):
			if (self.get(field) or 0) < 0:
				frappe.throw(_("{0} can't be negative.").format(self.meta.get_label(field)))

	def on_update(self):
		self.update_profile_weight()

	def update_profile_weight(self):
		"""The latest check-in sets the profile weight, which recalculates automatic targets."""
		if not self.weight_kg:
			return
		latest = frappe.get_all(
			"LL Check In",
			filters={"user": self.user, "weight_kg": [">", 0]},
			order_by="checkin_date desc, week desc, modified desc",
			pluck="name",
			limit=1,
		)
		if latest != [self.name] or not frappe.db.exists("LL Profile", self.user):
			return
		profile = frappe.get_doc("LL Profile", self.user)
		if flt(profile.weight_kg) != flt(self.weight_kg):
			profile.weight_kg = self.weight_kg
			profile.save(ignore_permissions=True)


def on_doctype_update():
	frappe.db.add_unique("LL Check In", ["user", "program", "week"], constraint_name="unique_user_program_week")

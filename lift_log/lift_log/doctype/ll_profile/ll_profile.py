import zoneinfo

import frappe
from frappe import _
from frappe.model.document import Document

from lift_log.permissions import enforce_record_user
from lift_log.targets import apply_automatic_targets

WEEKDAY_KEYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}


class LLProfile(Document):
	def validate(self):
		enforce_record_user(self)
		self.validate_values()
		apply_automatic_targets(self)

	def validate_values(self):
		if self.weight_kg and not 25 <= self.weight_kg <= 400:
			frappe.throw(_("Enter a body weight between 25 and 400 kg."))
		if self.height_cm and not 100 <= self.height_cm <= 250:
			frappe.throw(_("Enter a height between 100 and 250 cm."))
		if self.age and not 10 <= self.age <= 110:
			frappe.throw(_("Enter an age between 10 and 110."))
		if self.time_zone and self.time_zone not in zoneinfo.available_timezones():
			frappe.throw(_("Unknown time zone: {0}").format(self.time_zone))
		days = [d.strip().lower() for d in (self.training_days or "").split(",") if d.strip()]
		if any(d not in WEEKDAY_KEYS for d in days):
			frappe.throw(_("Training days must be a comma-separated list like mon,tue,wed."))
		self.training_days = ",".join(days)

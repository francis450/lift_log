"""AI endpoints (docs/05). Not built until M5 and M7: every call answers HTTP 501."""

import frappe
from frappe import _

from lift_log.api.utils import current_user


class AINotAvailable(frappe.ValidationError):
	http_status_code = 501


def _not_available():
	current_user()
	frappe.throw(_("AI features aren't set up on your server"), AINotAvailable)


@frappe.whitelist(methods=["POST"])
def estimate(text: str | None = None, image_base64: str | None = None, image_mime: str | None = None):
	_not_available()


@frappe.whitelist(methods=["POST"])
def suggest(date: str | None = None, meal: str | None = None):
	_not_available()


@frappe.whitelist(methods=["POST"])
def weekly_review(week: int | None = None, regenerate: bool = False):
	_not_available()


@frappe.whitelist(methods=["POST"])
def review_followup(week: int | None = None, question: str | None = None):
	_not_available()


@frappe.whitelist(methods=["POST"])
def apply_changes(week: int | None = None, accepted=None):
	_not_available()

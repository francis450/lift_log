import frappe
from frappe.model.document import Document

from lift_log.permissions import is_admin


class LLFoodItem(Document):
	def validate(self):
		# Only administrators (the seed loader) write library items; everyone else writes their own.
		if not is_admin():
			self.is_seed = 0
			self.user = frappe.session.user
		if self.is_seed:
			self.user = None
		elif not self.user:
			self.user = frappe.session.user
		if self.is_new() and self.user:
			self.owner = self.user


def get_permission_query_conditions(user=None):
	user = user or frappe.session.user
	if is_admin(user):
		return ""
	return f"(`tabLL Food Item`.is_seed = 1 or `tabLL Food Item`.owner = {frappe.db.escape(user)})"


def has_permission(doc, ptype=None, user=None, debug=False):
	user = user or frappe.session.user
	if is_admin(user):
		return True
	if doc.is_seed:
		return ptype in ("read", "select", "print")
	return not doc.owner or doc.owner == user

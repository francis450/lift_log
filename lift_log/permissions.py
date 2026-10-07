import frappe
from frappe import _

ROLE = "Lift Log User"
NOT_SET_UP = "This account isn't set up for Lift Log yet."


def is_admin(user: str | None = None) -> bool:
	return "System Manager" in frappe.get_roles(user or frappe.session.user)


def enforce_record_user(doc) -> None:
	"""Every record belongs to one user. Only a System Manager may write a record for someone else.

	New records are owned by their user, so the role's "If Owner" permissions apply even when an
	administrator (seed, migration) creates them.
	"""
	session_user = frappe.session.user
	if not doc.get("user"):
		doc.user = session_user
	if doc.user != session_user and not is_admin(session_user):
		frappe.throw(_("You can only save your own records."), frappe.PermissionError)
	if doc.is_new():
		doc.owner = doc.user

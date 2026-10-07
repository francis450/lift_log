import frappe
from frappe import _
from frappe.auth import LoginManager
from frappe.utils.password import set_encrypted_password

from lift_log.api.utils import current_user
from lift_log.permissions import NOT_SET_UP, ROLE


def _authenticate(usr: str, pwd: str) -> str:
	"""Check the password with LoginManager (lockouts and the auth log included) without starting a
	cookie session: the app authenticates every later call with an API token."""
	login_manager = LoginManager.__new__(LoginManager)
	login_manager.user = None
	login_manager.authenticate(user=usr, pwd=pwd)
	return login_manager.user


def _rotate_secret(user: str, create_key: bool = False) -> tuple[str, str]:
	api_key = frappe.db.get_value("User", user, "api_key")
	if not api_key and create_key:
		api_key = frappe.generate_hash(length=15)
		frappe.db.set_value("User", user, "api_key", api_key)
	api_secret = frappe.generate_hash(length=15)
	set_encrypted_password("User", user, api_secret, "api_secret")
	return api_key, api_secret


@frappe.whitelist(allow_guest=True, methods=["POST"])
def sign_in(usr: str, pwd: str) -> dict:
	user = _authenticate(usr, pwd)
	if ROLE not in frappe.get_roles(user):
		frappe.throw(_(NOT_SET_UP), frappe.PermissionError)

	api_key, api_secret = _rotate_secret(user, create_key=True)
	return {
		"api_key": api_key,
		"api_secret": api_secret,
		"user": user,
		"full_name": frappe.db.get_value("User", user, "full_name") or user,
		"has_profile": bool(frappe.db.exists("LL Profile", user)),
	}


@frappe.whitelist(methods=["POST"])
def sign_out() -> dict:
	"""Rotate the secret so the token stored on the phone stops working."""
	user = current_user()
	_rotate_secret(user)
	return {"ok": True}

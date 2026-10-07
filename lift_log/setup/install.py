import frappe

from lift_log.permissions import ROLE

SETTINGS_DEFAULTS = {
	"ai_enabled": 1,
	"model_quick": "claude-haiku-4-5-20251001",
	"model_vision": "claude-sonnet-5-5",
	"model_review": "claude-sonnet-5-5",
	"daily_ai_calls_per_user": 40,
	"max_image_mb": 5,
}


def before_install():
	# DocType permissions reference the role, so it must exist before the DocTypes sync.
	ensure_role()


def after_install():
	ensure_role()
	ensure_settings_defaults()


def after_migrate():
	ensure_role()


def ensure_role():
	if not frappe.db.exists("Role", ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": ROLE, "desk_access": 0}).insert(ignore_permissions=True)


def ensure_settings_defaults():
	settings = frappe.get_single("LL Settings")
	for field, value in SETTINGS_DEFAULTS.items():
		if not settings.get(field):
			settings.set(field, value)
	settings.save(ignore_permissions=True)

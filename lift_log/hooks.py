app_name = "lift_log"
app_title = "Lift Log"
app_publisher = "Lift Log"
app_description = "Personal gym and food log: backend for the Lift Log Android app"
app_email = "franciskamande2001@gmail.com"
app_license = "mit"

# Installation
# ------------

before_install = "lift_log.setup.install.before_install"
after_install = "lift_log.setup.install.after_install"
after_migrate = "lift_log.setup.install.after_migrate"

# Permissions
# -----------
# Seed foods are readable by everyone with the role; custom foods only by their owner.

permission_query_conditions = {
	"LL Food Item": "lift_log.lift_log.doctype.ll_food_item.ll_food_item.get_permission_query_conditions",
}

has_permission = {
	"LL Food Item": "lift_log.lift_log.doctype.ll_food_item.ll_food_item.has_permission",
}

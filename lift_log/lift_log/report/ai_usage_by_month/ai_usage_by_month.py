import frappe
from frappe import _


def execute(filters=None):
	"""Claude calls and tokens per month and feature, from LL AI Log (docs/05, cost guard)."""
	columns = [
		{"fieldname": "month", "label": _("Month"), "fieldtype": "Data", "width": 100},
		{"fieldname": "feature", "label": _("Feature"), "fieldtype": "Data", "width": 140},
		{"fieldname": "calls", "label": _("Calls"), "fieldtype": "Int", "width": 90},
		{"fieldname": "failed", "label": _("Failed"), "fieldtype": "Int", "width": 90},
		{"fieldname": "input_tokens", "label": _("Input tokens"), "fieldtype": "Int", "width": 130},
		{"fieldname": "output_tokens", "label": _("Output tokens"), "fieldtype": "Int", "width": 130},
		{"fieldname": "avg_latency_ms", "label": _("Avg latency (ms)"), "fieldtype": "Int", "width": 140},
	]
	data = frappe.db.sql(
		"""
		select date_format(creation, %(fmt)s) as month, feature, count(*) as calls,
			sum(case when ok = 1 then 0 else 1 end) as failed,
			sum(input_tokens) as input_tokens, sum(output_tokens) as output_tokens,
			round(avg(latency_ms)) as avg_latency_ms
		from `tabLL AI Log`
		group by month, feature
		order by month desc, feature
		""",
		{"fmt": "%Y-%m"},
		as_dict=True,
	)
	return columns, data

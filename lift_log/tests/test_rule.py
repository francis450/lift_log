import json
from pathlib import Path

from frappe.tests.utils import FrappeTestCase

from lift_log.rule import next_call, parse_rep_range

TABLE = json.loads((Path(__file__).parent / "rule_cases.json").read_text())


def _history(raw):
	return [
		{
			"date": s["date"],
			"deload": s.get("deload", False),
			"sets": [{"kg": kg, "amount": amount, "effort": effort} for kg, amount, effort in s["sets"]],
		}
		for s in raw
	]


class TestRuleTable(FrappeTestCase):
	"""The same cases as the app's nextCall() (src/lib/__tests__/nextCall.cases.json)."""

	def test_every_case(self):
		self.assertGreaterEqual(len(TABLE["cases"]), 15)
		for case in TABLE["cases"]:
			with self.subTest(case["name"]):
				result = next_call(
					TABLE["exercises"][case["exercise"]],
					case["target"],
					_history(case["history"]),
					case.get("reviewDeltaKg") or 0,
				)
				self.assertEqual(result, case["expect"])

	def test_parse(self):
		self.assertEqual(parse_rep_range("6-8"), (6, 8))
		self.assertEqual(parse_rep_range("5"), (5, 5))
		self.assertIsNone(parse_rep_range("max"))

import json
from pathlib import Path

from frappe.tests.utils import FrappeTestCase

from lift_log.rule import next_call, parse_rep_range

TABLE = json.loads((Path(__file__).parent / "rule_cases.json").read_text())


def _set(raw):
	"""[kg, amount, effort], [kg, amount, effort, side, set_no], or {kg, amount, rir, warmup, side, set_no}."""
	if isinstance(raw, dict):
		return dict(raw)
	kg, amount, effort, *side = raw
	return {"kg": kg, "amount": amount, "effort": effort, "side": side[0] if side else None, "set_no": side[1] if side else None}


def _history(raw):
	return [{"date": s["date"], "deload": s.get("deload", False), "sets": [_set(x) for x in s["sets"]]} for s in raw]


class TestRuleTable(FrappeTestCase):
	"""The same cases as the app's nextCall() (src/lib/__tests__/nextCall.cases.json)."""

	def test_every_case(self):
		self.assertGreaterEqual(len(TABLE["cases"]), 40)
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

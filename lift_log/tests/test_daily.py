from datetime import date, timedelta
from unittest.mock import patch

import frappe

from lift_log import trend
from lift_log.api import daily, today
from lift_log.tests.helpers import USER_A, USER_B, LiftLogTestCase

DAY = date(2026, 11, 24)


class TestDailyLog(LiftLogTestCase):
	def setUp(self):
		super().setUp()
		self.make_profile()

	def test_morning_and_evening_saves_merge(self):
		daily.save(
			log_date="2026-11-24",
			weight_kg=71.4,
			sleep_hours=6.5,
			pain=3,
			client_updated_at="2026-11-24T04:00:00Z",
		)
		out = daily.save(log_date="2026-11-24", steps=8432, client_updated_at="2026-11-24T18:00:00Z")
		self.assertEqual(out["weight_kg"], 71.4)
		self.assertEqual(out["sleep_hours"], 6.5)
		self.assertEqual(out["steps"], 8432)
		self.assertEqual(out["pain"], 3)
		self.assertEqual(out["pain_area"], "Lower back")
		self.assertEqual(frappe.db.count("LL Daily Log", {"user": USER_A}), 1)

	def test_blank_clears_and_zero_pain_is_kept(self):
		daily.save(log_date="2026-11-24", weight_kg=71.4, pain=0, client_updated_at="2026-11-24T04:00:00Z")
		out = daily.save(log_date="2026-11-24", weight_kg="", client_updated_at="2026-11-24T05:00:00Z")
		self.assertIsNone(out["weight_kg"])
		self.assertEqual(out["pain"], 0)

	def test_stale_write_gets_409(self):
		daily.save(log_date="2026-11-24", weight_kg=71.4, client_updated_at="2026-11-24T05:00:00Z")
		out = daily.save(log_date="2026-11-24", weight_kg=80, client_updated_at="2026-11-24T04:00:00Z")
		self.assertEqual(frappe.local.response.http_status_code, 409)
		self.assertEqual(out["stored"]["weight_kg"], 71.4)

	def test_validation(self):
		for bad in ({"weight_kg": 5}, {"sleep_hours": 30}, {"pain": 11}, {"steps": -10}):
			with self.subTest(bad), self.assertRaises(frappe.ValidationError):
				daily.save(log_date="2026-11-24", **bad)

	def test_records_are_private(self):
		daily.save(log_date="2026-11-24", weight_kg=71.4)
		frappe.set_user(USER_B)
		self.assertIsNone(daily.get("2026-11-24")["log"])

	def test_trend_needs_four_weigh_ins_a_week(self):
		for i in range(14):
			daily.save(log_date=str(DAY - timedelta(days=i)), weight_kg=71.2 - 0.05 * (13 - i))
		got = daily.get(str(DAY))["trend"]
		self.assertEqual(got["weigh_ins_7d"], 7)
		self.assertEqual(got["change_kg_per_week"], -0.35)
		recent = daily.recent(days=7, until=str(DAY))
		self.assertEqual(len(recent["days"]), 7)
		self.assertIsNotNone(recent["days"][-1]["avg_7d_kg"])

	@patch("lift_log.api.today.user_today", return_value=DAY)
	def test_today_carries_the_log(self, _today):
		daily.save(log_date=str(DAY), weight_kg=71.4)
		got = today.get(str(DAY))
		self.assertEqual(got["daily"]["weight_kg"], 71.4)
		self.assertIn("avg_7d_kg", got["weight_trend"])


class TestTrend(LiftLogTestCase):
	def test_three_weigh_ins_are_not_enough(self):
		weights = {DAY - timedelta(days=i): 71.0 for i in range(3)}
		self.assertEqual(trend.window_average(weights, DAY), (None, 3))
		weights[DAY - timedelta(days=5)] = 72.0
		self.assertEqual(trend.window_average(weights, DAY), (71.25, 4))

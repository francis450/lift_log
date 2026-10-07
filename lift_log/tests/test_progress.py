from datetime import date
from unittest.mock import patch

from lift_log.api import checkins, food, progress, sessions
from lift_log.tests.helpers import FOOD_6_OCT, SESSION_6_OCT, LiftLogTestCase


@patch("lift_log.api.progress.user_today", return_value=date(2026, 10, 7))
class TestProgress(LiftLogTestCase):
	def setUp(self):
		super().setUp()
		self.make_profile()

	def test_empty_block_uses_program_start_weights(self, _today):
		out = progress.summary(week=1)
		self.assertEqual(out["sessions"], {"done": 0, "planned_to_date": 2})
		self.assertEqual(out["protein_by_day"][0], {"date": "2026-10-05", "protein_g": None})
		lifts = {l["exercise"]: l for l in out["lifts"]}
		self.assertEqual(lifts["Barbell back squat"]["start_kg"], 40)
		self.assertEqual(lifts["Barbell bench press"]["start_kg"], 30)
		self.assertEqual(lifts["Conventional deadlift"]["start_kg"], 50)
		self.assertIsNone(lifts["Hip thrust"]["start_kg"])
		self.assertIsNone(lifts["Hip thrust"]["best"])
		self.assertEqual(len(out["lifts"]), 7)

	def test_logged_week(self, _today):
		sessions.save(**SESSION_6_OCT)
		food.save_day(**FOOD_6_OCT)
		checkins.save(week=1, checkin_date="2026-10-11", weight_kg=71.6, forearm_cm=29)
		out = progress.summary(week=1)
		self.assertEqual(out["sessions"], {"done": 1, "planned_to_date": 2})
		self.assertEqual(out["protein_target_g"], 130)
		self.assertEqual(out["protein_by_day"][1], {"date": "2026-10-06", "protein_g": 125})
		self.assertEqual(out["protein_days_hit"], 0)
		lifts = {l["exercise"]: l for l in out["lifts"]}
		self.assertEqual(lifts["Barbell back squat"]["best"], {"kg": 40, "amount": 8, "date": "2026-10-06"})
		self.assertEqual(lifts["Barbell Romanian deadlift"]["start_kg"], 40)
		self.assertEqual(out["bodyweight"], [{"week": 1, "kg": 71.6}])
		self.assertEqual(out["forearm"], [{"week": 1, "cm": 29}])

	def test_today_counts_once_trained(self, today_mock):
		today_mock.return_value = date(2026, 10, 6)
		self.assertEqual(progress.summary()["sessions"]["planned_to_date"], 1)
		sessions.save(**SESSION_6_OCT)
		self.assertEqual(progress.summary()["sessions"], {"done": 1, "planned_to_date": 2})

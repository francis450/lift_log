import frappe

from lift_log.api import ai
from lift_log.tests.helpers import USER_A, LiftLogTestCase


class TestAIStubs(LiftLogTestCase):
	def test_ai_endpoints_answer_501(self):
		frappe.set_user(USER_A)
		calls = (
			lambda: ai.estimate(text="2 chapati"),
			lambda: ai.suggest(date="2026-10-07", meal="lunch"),
			lambda: ai.weekly_review(week=1),
			lambda: ai.review_followup(week=1, question="Why?"),
			lambda: ai.apply_changes(week=1, accepted=[0]),
		)
		for call in calls:
			with self.assertRaises(ai.AINotAvailable) as ctx:
				call()
			self.assertEqual(ctx.exception.http_status_code, 501)

import unittest
from dataclasses import replace

from readiness import Visit, check_visit, example


class FirstVisitTests(unittest.TestCase):
    def test_missing_required_detail(self):
        visit = Visit("scheduled", "the stairwell")
        decision = check_visit(visit)
        self.assertEqual(decision.action, "ask")
        self.assertIn("the stairwell", decision.note)
        self.assertEqual(check_visit(replace(visit, request_sent=True)).action, "await_detail")

    def test_optional_or_complete_address(self):
        for visit in (Visit("scheduled"), Visit("scheduled", "the stairwell", True)):
            with self.subTest(visit=visit):
                self.assertEqual(check_visit(visit).action, "wait")

    def test_carrier_evidence_takes_priority(self):
        for stage, action in [("dispatched", "carrier_ops"), ("route_exception", "carrier_ops"),
                              ("confirmed_miss", "recover"), ("collected", "close"), ("new_status", "check_status")]:
            with self.subTest(stage=stage):
                self.assertEqual(check_visit(Visit(stage, "the stairwell")).action, action)
        self.assertEqual(check_visit(Visit("dispatched")).action, "wait")

    def test_open_request(self):
        followup = example("entrance")["followup"]
        self.assertEqual(followup["updated"]["action"], "wait")
        self.assertEqual(followup["disputed"]["action"], "verify_address")
        self.assertEqual(followup["left"]["action"], "carrier_ops")
        self.assertEqual(followup["pending"]["action"], "await_detail")

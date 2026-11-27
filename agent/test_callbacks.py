"""A carrier inquiry can outlive more than one update promised to the shopper."""
from datetime import timedelta
import unittest

from carrier import MockServices
from demo import run_case
from pickup import Case, handle


class CallbackTests(unittest.TestCase):
    def test_callback_deduplication(self):
        tools = MockServices()
        case = Case("P102")
        record = tools.cases[case.case_id]
        opened = tools.now
        self.assertEqual(handle(case, tools, record["sample"])["state"], "WAITING_CARRIER")

        tools.now = opened + timedelta(minutes=10)
        record.update(status="missed", misses=1)
        self.assertEqual(handle(case, tools, "")["state"], "OFFERED")
        tools.send_inquiry_update(case.case_id, "Duplicate delivery")

        tools.now = opened + timedelta(minutes=15)
        record["status"] = "unknown"
        waiting = handle(case, tools, "")
        self.assertEqual(waiting["state"], "WAITING_CARRIER")
        self.assertIn("19:00", waiting["message"])
        handle(case, tools, "")
        tools.now = opened + timedelta(minutes=30)
        handoff = handle(case, tools, "")
        self.assertEqual(handoff["state"], "HUMAN_REVIEW")
        handle(case, tools, "")
        tools.send_inquiry_update(case.case_id, "Duplicate delivery")

        inquiries = [call for call in tools.calls if call["tool"] == "carrier.ask_for_update"]
        notices = [call for call in tools.calls if call["tool"] == "support.send_inquiry_update"]
        self.assertEqual(len(inquiries), 1)
        self.assertEqual([call["at"] for call in notices],
                         [(opened + timedelta(minutes=n)).isoformat() for n in (10, 30)])
        self.assertEqual(notices[1]["result"], handoff["message"])

    def test_replay_sources(self):
        expected = {
            "P101": ["shopper_message", "shopper_message"],
            "P102": ["shopper_message", "timer"],
            "P111": ["carrier_event"],
            "P114": ["shopper_message", "shopper_selection", "shopper_message"],
            "P115": ["shopper_message"],
            "P116": ["shopper_message"],
        }
        for case_id, sources in expected.items():
            with self.subTest(case_id=case_id):
                row = run_case(case_id, scripted=True)
                self.assertEqual([turn["event_source"] for turn in row["turns"]], sources)
                if case_id in {"P114", "P115", "P116"}:
                    self.assertEqual(row["state"], "HUMAN_REVIEW")
                    self.assertEqual(row["bookings_created"], int(case_id == "P114"))
                    self.assertEqual(row["confirmation_notices_delivered"], 0)
                    self.assertFalse(row["autonomous_under_24h"])

    def test_stale_button_after_handoff(self):
        row = run_case("P104", slot="A")
        self.assertEqual(row["turns"][-1]["event_source"], "shopper_selection")
        self.assertEqual(row["state"], "HUMAN_REVIEW")
        self.assertEqual(row["bookings_created"], 0)
        self.assertEqual(row["confirmation_notices_delivered"], 0)
        self.assertFalse(row["autonomous_under_24h"])

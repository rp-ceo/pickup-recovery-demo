"""Carrier evidence, promised callbacks and time-limited pickup offers."""
from datetime import timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from carrier import BOOKING_LEAD, MockServices, TimeZoneConfigurationError
from pickup import Case, handle


class PickupLifecycleTests(unittest.TestCase):
    def open_case(self, case_id):
        tools = MockServices()
        case = Case(case_id)
        handle(case, tools, tools.cases[case_id]["sample"])
        return case, tools

    def test_invalid_window_label(self):
        for bad_label in (None, "", "  ", "Thu 26 Nov, 10:00–12:00 CET"):
            with self.subTest(bad_label=bad_label):
                tools = MockServices()
                tools.slots["A"] = bad_label
                case = Case("P101")
                handle(case, tools, tools.cases["P101"]["sample"])
                self.assertEqual(list(case.offered), ["B"])
                handle(case, tools, "", selected_slot="A", offer_number=case.offer_number)
                self.assertEqual((tools.bookings, tools.notices), ({}, {}))
                self.assertEqual(handle(case, tools, "", selected_slot="B")["state"], "RESOLVED")

    def test_slot_duration(self):
        case, tools = self.open_case("P101")
        tools.slot_duration_minutes["A"] = 60
        self.assertEqual(handle(case, tools, "", selected_slot="A")["state"], "SLOT_CHANGED")
        self.assertFalse(tools.bookings)
        tools.slot_duration_minutes["B"] = 0
        self.assertEqual(handle(case, tools, "")["state"], "HUMAN_REVIEW")
        self.assertFalse(tools.notices)

    def test_unavailable_start(self):
        for raw_start in (None, "", "bad", "2026-11-25T10:00:00"):
            with self.subTest(raw_start=raw_start):
                data = json.loads(Path(__file__).with_name("fixtures.json").read_text(encoding="utf-8"))
                if raw_start is None:
                    del data["slot_starts"]["A"]
                else:
                    data["slot_starts"]["A"] = raw_start
                tools = MockServices(data)
                self.assertEqual(list(tools.offer_slots("P101")), ["B"])

    def test_unknown_time_zone(self):
        data = json.loads(Path(__file__).with_name("fixtures.json").read_text(encoding="utf-8"))
        data["slot_timezone"] = "Atlantis/MissingZone"
        with self.assertRaisesRegex(TimeZoneConfigurationError, "Atlantis/MissingZone"):
            MockServices(data)

    def test_missing_zone_data_at_startup(self):
        env = dict(os.environ, PYTHONTZPATH="", PYTHONPATH="")
        app = Path(__file__).with_name("demo.py")
        result = subprocess.run([sys.executable, "-S", "-B", str(app), "P101", "--json"],
                                capture_output=True, text=True, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("py -3 -m pip install tzdata", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_changed_end_time(self):
        case, tools = self.open_case("P132")
        self.assertEqual(handle(case, tools, "", selected_slot="A")["state"], "BOOKING_UNCERTAIN")
        tools.bookings[case.case_id]["end"] = "2026-11-25T13:00:00+01:00"
        self.assertEqual(handle(case, tools, "")["state"], "HUMAN_REVIEW")
        self.assertEqual(len(tools.bookings), 1)
        self.assertFalse(tools.notices)

    def test_offer_at_deadline(self):
        for timer_first in (False, True):
            with self.subTest(timer_first=timer_first):
                case, tools = self.open_case("P101")
                tools.now += timedelta(hours=48)
                if timer_first:
                    self.assertEqual(handle(case, tools, "")["state"], "AWAITING_REPLY")
                    self.assertFalse(tools.queue)
                tools.slot_starts["A"] += timedelta(days=3)
                tools.slots["A"] = "Sat 28 Nov, 08:00–12:00 CET"
                result = handle(case, tools, "", selected_slot="A", offer_number=1)
                self.assertEqual(result["state"], "SLOT_CHANGED")
                self.assertIn("Sat 28 Nov", result["message"])
                handle(case, tools, "", selected_slot="A", offer_number=1)
                self.assertFalse(tools.bookings)
                self.assertEqual(handle(case, tools, "", selected_slot="A", offer_number=2)["state"], "RESOLVED")

    def test_offer_before_deadline(self):
        case, tools = self.open_case("P101")
        tools.now = tools.slot_starts["A"] - BOOKING_LEAD - timedelta(seconds=1)
        self.assertEqual(handle(case, tools, "", selected_slot="A")["state"], "RESOLVED")

    def test_remaining_slot_keeps_its_link(self):
        case, tools = self.open_case("P101")
        tools.now = tools.local_time(tools.slot_starts["A"] - BOOKING_LEAD)
        changed = handle(case, tools, "")
        self.assertEqual((changed["state"], set(case.offered), case.offer_number), ("SLOT_CHANGED", {"B"}, 1))
        handle(case, tools, "", selected_slot="A", offer_number=1)
        self.assertFalse(tools.bookings)
        self.assertEqual(handle(case, tools, "", selected_slot="B", offer_number=1)["state"], "RESOLVED")
        self.assertEqual(tools.bookings["P101"]["slot"], "B")

    def test_email_lifetime(self):
        case, tools = Case("P101"), MockServices()
        tools.slot_starts["B"] += timedelta(days=1)
        tools.slots["B"] = "Fri 27 Nov, 12:00–16:00 CET"
        handle(case, tools, tools.cases["P101"]["sample"])
        tools.now += timedelta(hours=48) - timedelta(seconds=1)
        self.assertEqual(handle(case, tools, "", selected_slot="B", offer_number=1)["state"], "RESOLVED")

    def test_callback_delivery_time(self):
        for minutes, expected_late in ((30, 0), (45, 15)):
            with self.subTest(minutes=minutes):
                case, tools = self.open_case("P102")
                due = tools.now + timedelta(minutes=30)
                tools.now += timedelta(minutes=minutes)
                self.assertEqual(handle(case, tools, "")["state"], "HUMAN_REVIEW")
                handle(case, tools, "")
                self.assertEqual(tools.callback_receipts, [
                    {"case_id": case.case_id, "inquiry": "Q-P102", "due_at": due.isoformat(),
                     "delivered_at": tools.now.isoformat(), "overdue": bool(expected_late),
                     "minutes_late": expected_late}])
                self.assertFalse(tools.pending_inquiry_updates)

    def test_scan_handoff(self):
        case, tools = self.open_case("P102")
        tools.now += timedelta(minutes=30)
        handle(case, tools, "")
        tools.now += timedelta(minutes=5)
        tools.cases[case.case_id]["status"] = "collected"
        carrier_event = handle(case, tools, "")
        handle(case, tools, "")
        reply = handle(case, tools, "Did you get the collection scan?")
        self.assertEqual(carrier_event["state"], "HUMAN_REVIEW")
        self.assertIn("carrier now reports", reply["message"])
        self.assertIn("collected", reply["message"])
        task = tools.queue[case.case_id]
        self.assertEqual(task["owner"], "Support Operations")
        self.assertEqual(task["latest_carrier_record"]["status"], "collected")
        self.assertIn("reported collection scan", task["next_step"])
        self.assertTrue(any("Did you get" in line for line in task["evidence"]))
        self.assertEqual(sum(call["tool"] == "support.handoff" for call in tools.calls), 1)
        self.assertEqual(sum("status=collected" in line for line in task["evidence"]), 1)
        self.assertEqual((tools.bookings, tools.notices), ({}, {}))

    def test_invalid_evidence_after_handoff(self):
        case, tools = self.open_case("P105")
        financial_task = tools.queue[case.case_id]["next_step"]
        tools.cases[case.case_id]["status"] = "collected"
        handle(case, tools, "")
        self.assertEqual(tools.queue[case.case_id]["next_step"], financial_task)
        tools.cases[case.case_id]["status"] = None
        reply = handle(case, tools, "")
        self.assertIn("fresh carrier status", reply["message"])
        self.assertEqual(tools.queue[case.case_id]["owner"], "Merchant Operations")
        self.assertFalse(tools.bookings)

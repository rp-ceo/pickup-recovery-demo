"""Carrier and shopper events can arrive between an offer, a booking and a notice."""
from datetime import timedelta
import unittest

from carrier import MockServices
from pickup import Case, handle


class CarrierChangeTests(unittest.TestCase):
    def start(self, case_id, carrier_first=False):
        services, case = MockServices(), Case(case_id)
        record = services.cases[case_id]
        handle(case, services, "" if carrier_first else record["sample"], carrier_event=carrier_first)
        return case, services, record

    def test_quote_at_contract_limit(self):
        case, services, record = self.start("P101")
        record["carrier_quote_eur_cents"] = services.merchant_policies["demo-store"]["max_repeat_eur_cents"]
        result = handle(case, services, "Thursday works for me")
        self.assertEqual(result["state"], "RESOLVED")
        self.assertEqual((len(services.bookings), len(services.notices)), (1, 1))

    def test_quote_changes_after_offer(self):
        for quote in (401, -1, None, "350", True):
            with self.subTest(quote=quote):
                case, services, record = self.start("P101")
                record["carrier_quote_eur_cents"] = quote
                handle(case, services, "Thursday works for me")
                self.assertEqual(services.queue["P101"]["owner"], "Merchant Operations")
                self.assertFalse(services.bookings)
                self.assertFalse(services.notices)

    def test_missing_contract_limit(self):
        case, services = Case("P101"), MockServices()
        del services.merchant_policies["demo-store"]["max_repeat_eur_cents"]
        handle(case, services, "", carrier_event=True)
        self.assertEqual(services.queue["P101"]["owner"], "Merchant Operations")
        self.assertFalse(case.offered)

    def test_address_flag_before_notice(self):
        for case_id in ("P132", "P108"):
            with self.subTest(case_id=case_id):
                case, services, record = self.start(case_id)
                handle(case, services, "", selected_slot="A", offer_number=case.offer_number)
                services.now += timedelta(minutes=1)
                record["missing_field"] = "building entrance"
                result = handle(case, services, "", carrier_event=True)
                self.assertEqual(result["state"], "HUMAN_REVIEW")
                task = services.queue[case_id]
                self.assertEqual(task["owner"], "Support Operations")
                self.assertIn("address", task["next_step"])
                self.assertIn("building entrance", " ".join(task["evidence"]))
                self.assertIn(services.bookings[case_id]["reference"], " ".join(task["evidence"]))
                handle(case, services, "", carrier_event=True)
                self.assertEqual((len(services.bookings), len(services.notices)), (1, 0))
                self.assertIsNone(case.resolved_at)

    def test_address_clearance_notice(self):
        for was_carrier_event in (False, True):
            with self.subTest(carrier_event=was_carrier_event):
                case, services, record = self.start("P106")
                services.now += timedelta(minutes=10)
                del record["missing_field"]
                self.assertEqual(handle(case, services, "", carrier_event=was_carrier_event)["state"], "OFFERED")
                delivered_at = services.now
                self.assertEqual(case.waiting_since, delivered_at)
                self.assertTrue(services.offer_receipts[case.case_id, case.offer_number])
                services.now += timedelta(hours=11, minutes=59)
                handle(case, services, "", carrier_event=True)
                self.assertEqual(case.waiting_since, delivered_at)
                self.assertEqual(len(services.offer_receipts), 1)
                services.now += timedelta(minutes=1)
                self.assertEqual(handle(case, services, "")["state"], "OFFERED")
                self.assertEqual(case.waiting_since, delivered_at)

    def test_unreachable_shopper(self):
        case, services, record = self.start("P106")
        record.update(missing_field=None, offer_delivery_fails=True)
        handle(case, services, "")
        self.assertEqual(case.state, "HUMAN_REVIEW")
        self.assertIsNone(case.waiting_since)
        self.assertFalse(case.offered)
        self.assertFalse(services.bookings)

    def test_offer_in_callback(self):
        case, services, record = self.start("P102")
        services.now += timedelta(minutes=10)
        record.update(status="missed", misses=1)
        handle(case, services, "", carrier_event=True)
        self.assertEqual(case.state, "OFFERED")
        self.assertEqual(case.waiting_since, services.now)
        self.assertTrue(services.offer_receipts[case.case_id, case.offer_number])
        self.assertEqual(len(services.callback_receipts), 1)
        self.assertEqual(services.callback_receipts[0]["delivered_at"], services.now.isoformat())
        self.assertFalse(any(call["tool"] == "support.send_pickup_options" for call in services.calls))

    def test_undelivered_callback_offer(self):
        case, services, record = self.start("P102")
        record.update(status="missed", misses=1, offer_delivery_fails=True)
        result = handle(case, services, "", carrier_event=True)
        self.assertEqual(case.state, "HUMAN_REVIEW")
        self.assertFalse(services.offer_receipts)
        self.assertEqual(len(services.callback_receipts), 1)
        self.assertEqual(services.inquiry_updates["Q-P102"], result["message"])

    def test_revised_window_list(self):
        case, services, record = self.start("P118", carrier_first=True)
        original = case.offer_number
        record["slots"] = ["B"]
        changed = handle(case, services, "", carrier_event=True)
        self.assertEqual(changed["state"], "SLOT_CHANGED")
        self.assertIn("Thu 26 Nov", changed["message"])
        self.assertEqual(list(case.offered), ["B"])
        self.assertEqual(len(services.offer_receipts), 2)
        self.assertTrue(services.offer_receipts[case.case_id, case.offer_number])
        for click in ("A", "B"):
            refused = handle(case, services, "", selected_slot=click, offer_number=original)
            self.assertIn(case.offered["B"], refused["message"])
            self.assertFalse(services.bookings)
        handle(case, services, "", selected_slot="B", offer_number=case.offer_number)
        self.assertEqual(services.bookings[case.case_id]["slot"], "B")
        self.assertEqual(len(services.notices), 1)

    def test_future_attempt_scan(self):
        case, services = Case("P101"), MockServices()
        services.cases[case.case_id]["attempted_at"] = (services.now + timedelta(days=2)).isoformat()
        handle(case, services, "", carrier_event=True)
        self.assertEqual(case.state, "HUMAN_REVIEW")
        self.assertIsNone(case.first_confirmed_miss_at)
        self.assertFalse(case.offered)
        self.assertIn("future", " ".join(services.queue[case.case_id]["evidence"]))

    def test_scan_after_repeat_miss(self):
        case, services = Case("P104"), MockServices()
        record = services.cases[case.case_id]
        record["misses"] = 3
        initial = handle(case, services, "", carrier_event=True)
        self.assertIn("3 missed attempts", initial["message"])
        record["status"] = "collected"
        handle(case, services, "", carrier_event=True)
        task = services.queue[case.case_id]
        self.assertEqual(task["owner"], "Support Operations")
        self.assertIn("reported collection scan", task["next_step"])
        self.assertIn("new pickup on hold", task["next_step"])
        self.assertEqual((len(services.bookings), len(services.notices)), (0, 0))

    def test_scan_timestamps(self):
        for case_id in ("P101", "P104"):
            with self.subTest(case_id=case_id):
                case, services, record = self.start(case_id)
                self.assertEqual(case.first_confirmed_miss_at, services.now)
                if case.state == "OFFERED":
                    handle(case, services, "", selected_slot="A", offer_number=case.offer_number)
                original_state, scheduling_time = case.state, case.resolved_at
                services.now += timedelta(days=1)
                observed = services.now
                record["status"] = "collected"
                result = handle(case, services, "", carrier_event=True)
                self.assertEqual(case.state, original_state)
                self.assertEqual(case.collection_scan_observed_at, observed)
                self.assertIsNone(case.collected_at)
                self.assertIn("collect", result["message"])
                self.assertNotIn("is confirmed for", result["message"])
                services.now += timedelta(minutes=5)
                actual = observed - timedelta(minutes=20)
                record["collected_at"] = actual.isoformat()
                handle(case, services, "", carrier_event=True)
                handle(case, services, "", carrier_event=True)
                self.assertEqual((case.collection_scan_observed_at, case.collected_at), (observed, actual))
                self.assertEqual(case.resolved_at, scheduling_time)
                self.assertEqual(len(services.notices), int(original_state == "RESOLVED"))
                self.assertEqual(sum("scan first observed" in line for line in case.evidence), 1)
                self.assertEqual(sum("carrier-reported collection time" in line for line in case.evidence), 1)

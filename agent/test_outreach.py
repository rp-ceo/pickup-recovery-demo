import unittest

from demo import run_case


class OutboundPickupTests(unittest.TestCase):
    def test_duplicate_carrier_alert(self):
        case = run_case("P118", scripted=True)
        self.assertEqual(case["origin"], "carrier")
        first, duplicate, selection = case["turns"]
        self.assertEqual([first["state"], duplicate["state"], selection["state"]],
                         ["OFFERED", "OFFERED", "RESOLVED"])
        self.assertFalse(any(c["tool"] == "carrier.book_once" for c in first["tool_calls"] + duplicate["tool_calls"]))
        receipts = [call["result"] for turn in case["turns"] for call in turn["tool_calls"]
                    if call["tool"] == "support.send_pickup_options"]
        self.assertEqual(len(receipts), 1)
        self.assertIn("Wed 25 Nov", receipts[0]["message"])
        self.assertTrue(receipts[0]["delivery_receipt"])
        self.assertEqual(case["shopper_help_contacts"], 0)
        self.assertEqual((case["pickup_offers_delivered"], case["bookings_created"],
                          case["confirmation_notices_delivered"]), (1, 1, 1))

    def test_unreachable_offer(self):
        case = run_case("P121", slot="A")
        self.assertEqual(case["state"], "HUMAN_REVIEW")
        self.assertEqual(case["owner"], "Support Operations")
        self.assertEqual((case["pickup_offers_delivered"], case["bookings_created"],
                          case["confirmation_notices_delivered"]), (0, 0, 0))

    def test_callback_lateness(self):
        for delayed, minutes_late in [(False, 0), (True, 15)]:
            with self.subTest(delayed=delayed):
                case = run_case("P102", advance_minutes=45, late_timer=delayed)
                receipt, = case["carrier_callback_receipts"]
                self.assertEqual(receipt["minutes_late"], minutes_late)
                self.assertEqual(receipt["overdue"], delayed)
                self.assertEqual(case["owner"], "Support Operations")

    def test_inbound_reply(self):
        case = run_case("P101", scripted=True)
        self.assertEqual(case["origin"], "shopper")
        self.assertEqual(case["pickup_offers_delivered"], 0)
        self.assertEqual(case["confirmation_notices_delivered"], 1)
        self.assertEqual(case["shopper_help_contacts"], 1)
        self.assertEqual(case["repeat_shopper_help_contacts"], 0)

    def test_repeat_help_contact(self):
        case = run_case("P117", scripted=True)
        self.assertEqual(case["shopper_help_contacts"], 2)
        self.assertEqual(case["repeat_shopper_help_contacts"], 1)
        self.assertEqual(case["bookings_created"], 0)

    def test_collection_scan(self):
        for case_id, booked, owner in (("P125", 1, "Pickup monitoring"), ("P127", 0, "Support Operations")):
            with self.subTest(case_id=case_id):
                case = run_case(case_id, scripted=True)
                self.assertIsNotNone(case["first_confirmed_miss_at"])
                self.assertIsNone(case["turns"][0]["collection_scan_observed_at"])
                self.assertLess(case["collected_at"], case["collection_scan_observed_at"])
                self.assertEqual(case["turns"][-1]["collection_scan_observed_at"], case["collection_scan_observed_at"])
                self.assertEqual(case["confirmation_notices_delivered"], booked)
                self.assertEqual(case["owner"], owner)

    def test_stale_button(self):
        case = run_case("P126", scripted=True)
        withdrawn, expired, current = case["turns"][1:]
        self.assertEqual(withdrawn["owner"], "Shopper")
        self.assertEqual(expired["state"], "NEEDS_SLOT_CHOICE")
        self.assertIn("offer 1", expired["event"])
        self.assertIn("offer 2", current["event"])
        self.assertEqual(case["pickup_offers_delivered"], 2)
        self.assertEqual((case["bookings_created"], case["confirmation_notices_delivered"]), (1, 1))

"""Customer acceptance checks. Run with python3 agent/test_customer_messages.py."""
from datetime import timedelta
import unittest

from carrier import MockServices
from demo import run_case
from pickup import Case, handle


OFFER = ("OFFERED",)
REVIEW = ("HUMAN_REVIEW",)
CHECK_FIRST = ("NEEDS_CLARIFICATION", "HUMAN_REVIEW")
CHECK_ADDRESS = (*CHECK_FIRST, "NEED_ADDRESS")
SUPPORT = "Support Operations"
MERCHANT = "Merchant Operations"

MESSAGES = [
    ("P101", "Nobody came to collect my return. Could I get a new pickup?", OFFER, None),
    ("P101", "Could I get compensation for this missed collection?", REVIEW, MERCHANT),
    ("P101", "Can I talk to a real person about my pickup?", REVIEW, SUPPORT),
    ("P101", "Both pickup attempts failed. What happens now?", REVIEW, SUPPORT),
    ("P101", "Can someone check this for me?", CHECK_FIRST, None),
    ("P101", "The driver is outside now for the pickup. Please tell me what to hand him.", CHECK_FIRST, None),
    ("P101", "The driver is five minutes away. Should I wait for my pickup?", CHECK_FIRST, None),
    ("P101", "The courier has the box now. Can you check the pickup status?", CHECK_FIRST, None),
    ("P101", "I took the parcel to the drop-off point after the missed pickup.", CHECK_FIRST, None),
    ("P101", "I changed my mind about returning this. The pickup is no longer needed.", CHECK_FIRST, None),
    ("P101", "Please call off tomorrow’s pickup; I’m keeping the item.", CHECK_FIRST, None),
    ("P101", "No courier on Monday and no courier today. Both days I waited for my pickup.", REVIEW, SUPPORT),
    ("P101", "I stayed home for two pickups and nobody came for either of them.", REVIEW, SUPPORT),
    ("P101", "I have moved. The pickup address on my return is wrong.", CHECK_ADDRESS, None),
    ("P101", "My pickup address is wrong. Can I change it before you send another courier?", CHECK_ADDRESS, None),
    ("P101", "Could someone from your team call me about my missed pickup?", REVIEW, SUPPORT),
    ("P101", "I already have a pickup. When will I get my refund?", REVIEW, None),
    ("P101", "My order never arrived.", CHECK_FIRST, None),
    ("P101", "Do I have to pay for the replacement pickup?", REVIEW, MERCHANT),
    ("P101", "No compensation needed. I just want to reschedule the pickup.", OFFER, None),
    ("P101", "Please don’t cancel my pickup; I just need to see the available times.",
     ("OFFERED", "NEEDS_CLARIFICATION"), None),
    ("P101", "It was not collected. The packaging is still here. Could you rebook my pickup?", OFFER, None),
    ("P101", "How will I know if my parcel was collected? Can you check the pickup?", CHECK_FIRST, None),
    ("P112", "Is the courier still coming to collect my parcel?", ("WINDOW_OPEN",), None),
    ("P102", "My collection window has ended. Is the courier still on the way?", ("WAITING_CARRIER",), None),
]


def open_offer(case_id="P101"):
    tools = MockServices()
    case = Case(case_id)
    handle(case, tools, tools.cases[case_id]["sample"])
    return case, tools


class CustomerMessageTests(unittest.TestCase):
    def test_initial_message(self):
        for case_id, message, expected, owner in MESSAGES:
            with self.subTest(case=case_id, message=message):
                result = run_case(case_id, message)
                self.assertIn(result["state"], expected)
                if owner is not None:
                    self.assertEqual(result["owner"], owner)

    def test_change_after_slot_selection(self):
        for case_id, delivered_before_change in (("P101", 1), ("P107", 0), ("P108", 0)):
            with self.subTest(case=case_id):
                case, tools = open_offer(case_id)
                handle(case, tools, "", selected_slot="A", offer_number=case.offer_number)
                handle(case, tools, "Actually I need Thursday, please.")
                tools.now += timedelta(minutes=1)
                handle(case, tools, "")
                self.assertEqual(case.state, "HUMAN_REVIEW")
                self.assertEqual(len(tools.bookings), 1)
                self.assertEqual(len(tools.notices), delivered_before_change)

    def test_old_button_after_new_information(self):
        for message in ("Please call off tomorrow’s pickup; I’m keeping the item.",
                        "The driver is outside now for the pickup.",
                        "My pickup address is wrong. Can you change it before sending the courier?"):
            with self.subTest(message=message):
                case, tools = open_offer()
                old_offer = case.offer_number
                handle(case, tools, message)
                handle(case, tools, "", selected_slot="A", offer_number=old_offer)
                self.assertFalse(tools.bookings)

    def test_unanswered_email_overnight(self):
        case, tools = open_offer()
        tools.now += timedelta(minutes=719)
        handle(case, tools, "")
        tools.now += timedelta(minutes=1)
        handle(case, tools, "")
        self.assertEqual(case.state, "OFFERED")
        self.assertFalse(tools.queue)
        self.assertFalse(tools.bookings)

    def test_typed_preference_followed_by_click(self):
        for message in ("A", "Wednesday works"):
            case, tools = open_offer()
            self.assertEqual(handle(case, tools, message)["state"], "RESOLVED")
            handle(case, tools, "", selected_slot="A", offer_number=case.offer_number)
            self.assertEqual(len(tools.notices), 1)
            self.assertEqual(len(tools.bookings), 1)


if __name__ == "__main__":
    unittest.main()

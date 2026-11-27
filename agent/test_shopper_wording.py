import unittest

from carrier import MockServices
from demo import run_case
from intent import read_intent
from pickup import Case, handle


class ShopperWordingTests(unittest.TestCase):
    def test_contradictory_shopper_report(self):
        messages = {
            "already_collected": [
                "The courier picked it up ten minutes ago. Do I need to do anything about the missed pickup?",
                "The driver just picked the box up.",
            ],
            "repeat_miss": [
                "I was in all day. This is the third missed pickup.",
                "That's our 4th failed collection.",
                "My last three pickup attempts failed.",
            ],
            "address_change": [
                "I need to change the location for my pickup. Can you collect it from my office instead?",
                "Can you pick the parcel up from my office instead of home?",
            ],
        }
        for intent, phrases in messages.items():
            for phrase in phrases:
                with self.subTest(intent=intent, message=phrase):
                    self.assertEqual(read_intent(phrase), intent)
                    result = run_case("P101", text=phrase, slot="A")
                    self.assertEqual([turn["state"] for turn in result["turns"]], ["HUMAN_REVIEW"] * 2)
                    self.assertEqual(result["owner"], "Support Operations")
                    self.assertFalse(result["bookings_created"])
                    self.assertFalse(result["confirmation_notices_delivered"])
                    self.assertFalse(result["autonomous_under_24h"])

    def test_choices_and_contact_counts(self):
        for text, button, state in (
            ("I prefer the second one.", "B", "RESOLVED"),
            ("I'd like to go with Wednesday morning, thanks.", "A", "RESOLVED"),
            ("How do I select a slot?", "A", "OFFERED"),
        ):
            with self.subTest(message=text):
                result = run_case("P101", reply=text, slot=button)
                self.assertEqual([turn["state"] for turn in result["turns"]], ["OFFERED", state, "RESOLVED"])
                self.assertEqual(result["shopper_help_contacts"], 1)
                self.assertEqual(result["repeat_shopper_help_contacts"], 0)
                self.assertEqual(result["bookings_created"], 1)
                self.assertEqual(result["confirmation_notices_delivered"], 1)

    def test_conflicting_preferences(self):
        for phrase in (
            "I prefer Wednesday morning, but collect the parcel from my office instead.",
            "I'd like to go with Wednesday morning if you can waive the fee.",
        ):
            with self.subTest(message=phrase):
                result = run_case("P101", reply=phrase, slot="A")
                self.assertEqual(result["state"], "HUMAN_REVIEW")
                self.assertFalse(result["bookings_created"])
                self.assertEqual(result["repeat_shopper_help_contacts"], 1)

    def test_unavailable_preference_keeps_link(self):
        case, tools = Case("P101"), MockServices()
        handle(case, tools, "", carrier_event=True)
        handle(case, tools, "I prefer Wednesday evening.")
        self.assertFalse(tools.queue)
        self.assertFalse(tools.bookings)
        handle(case, tools, "", selected_slot="A", offer_number=1)
        self.assertEqual(tools.bookings["P101"]["window"], "Wed 25 Nov, 08:00–12:00 CET")

    def test_ordinal_points_to_the_displayed_order(self):
        tools = MockServices()
        tools.cases["P101"]["slots"] = ["B", "A"]
        case = Case("P101")
        handle(case, tools, tools.cases["P101"]["sample"])
        state = handle(case, tools, "I prefer the first one.", selected_slot="A", offer_number=case.offer_number)
        self.assertEqual(state["state"], "HUMAN_REVIEW")
        self.assertFalse(tools.bookings)


if __name__ == "__main__":
    unittest.main()

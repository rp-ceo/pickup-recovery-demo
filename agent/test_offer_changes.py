import unittest

from carrier import MockServices
from local_model import ollama_intent
from pickup import Case, handle


class OfferChangeTests(unittest.TestCase):
    def offer(self):
        services = MockServices()
        case = Case("P101")
        handle(case, services, services.cases[case.case_id]["sample"])
        return case, services

    def test_withdrawn_offer(self):
        for message in ("Wait, that address isn’t mine.", "Something else has happened to the parcel.",
                        "Call off the collection. I'm keeping the item.", "The driver is at my door now."):
            with self.subTest(message=message):
                case, services = self.offer()
                original = case.offer_number
                result = handle(case, services, message, message_id="change")
                self.assertEqual(result["state"], "HUMAN_REVIEW")
                self.assertFalse(case.offered)
                self.assertTrue(any(message in fact for fact in services.queue["P101"]["evidence"]))
                for followup in ({"selected_slot": "A", "offer_number": original}, {},
                                 {"message_id": "change", "selected_slot": "B", "offer_number": original}):
                    text = message if "message_id" in followup else ""
                    self.assertEqual(handle(case, services, text, **followup)["state"], "HUMAN_REVIEW")
                self.assertFalse(services.bookings)
                self.assertFalse(services.notices)

    def test_ambiguous_choice(self):
        for text in ("Great, thanks!", "What times are available?", "Wednesday?"):
            case, services = self.offer()
            self.assertEqual(handle(case, services, text)["state"], "OFFERED")
            self.assertFalse(services.bookings)
        case, services = self.offer()
        self.assertEqual(handle(case, services, "Thursday works", selected_slot="A",
                                offer_number=case.offer_number)["state"], "HUMAN_REVIEW")
        self.assertFalse(services.bookings)

    def test_shopper_corrections(self):
        cases = (("Please change my collection address.", "Support Operations"),
                 ("I dropped the parcel off at the post office after the missed pickup.", "Support Operations"),
                 ("Could somebody from your support team phone me about my pickup?", "Support Operations"),
                 ("No driver yesterday and no driver today. Can we sort this out?", "Support Operations"),
                 ("I have a pickup. When should I expect my refund?", "Returns Support"))
        for text, owner in cases:
            with self.subTest(text=text):
                tools = MockServices()
                case = Case("P101")
                self.assertEqual(handle(case, tools, text)["state"], "HUMAN_REVIEW")
                self.assertEqual(tools.queue["P101"]["owner"], owner)
                self.assertFalse(case.offered)

    def test_separate_fee_question(self):
        case, services = self.offer()
        handle(case, services, "I don't need compensation, but who pays for my replacement pickup?")
        self.assertEqual(services.queue["P101"]["owner"], "Merchant Operations")

    def test_model_address_intent(self):
        label = ollama_intent("That destination is out of date", "sample", lambda _: '{"intent":"address_change"}')
        tools = MockServices()
        case = Case("P101")
        self.assertEqual(handle(case, tools, "That destination is out of date", classify=lambda _: label)["state"],
                         "HUMAN_REVIEW")
        self.assertIn("address", tools.queue["P101"]["next_step"])


if __name__ == "__main__":
    unittest.main()

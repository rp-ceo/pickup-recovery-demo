import json
import unittest
from collections import Counter

from demo import run_case
from intent import read_intent
from local_model import classify_reply


class ModelFallbackTests(unittest.TestCase):
    def test_rules_keep_their_result(self):
        outcomes = Counter()
        for text in ("Nobody came to collect my package", "I want compensation", "Did the courier collect my parcel?"):
            with self.subTest(text=text):
                result = classify_reply(text, "local", lambda _: self.fail("Unexpected model call"), outcomes=outcomes)
                self.assertEqual(result, read_intent(text))
        self.assertFalse(outcomes)

    def test_unresolved_reply_goes_to_the_model(self):
        text = "The buzzer on file points to where I used to live."
        self.assertEqual(read_intent(text), "unknown")
        calls = []

        def reply(payload):
            calls.append(payload["messages"][-1])
            return json.dumps({"intent": "address_change"})

        outcomes = Counter()
        result = run_case("P101", text=text, classify=lambda msg: classify_reply(msg, "local", reply, outcomes=outcomes))
        self.assertEqual(calls, [{"role": "user", "content": text}])
        self.assertEqual(outcomes, {"classified": 1})
        self.assertEqual((result["state"], result["bookings_created"]), ("HUMAN_REVIEW", 0))

    def test_provider_outcomes(self):
        text = "That destination is out of date"

        def offline(_):
            raise TimeoutError()

        for provider, outcome in ((offline, "unavailable"), (lambda _: "not JSON", "invalid_response"),
                                  (lambda _: '{"intent":"book","slot":"A"}', "invalid_response"),
                                  (lambda _: '{"intent":"unknown"}', "unresolved")):
            with self.subTest(outcome=outcome):
                outcomes = Counter()
                self.assertEqual(classify_reply(text, "local", provider, outcomes=outcomes), "unknown")
                self.assertEqual(outcomes, {outcome: 1})

    def test_booking_works_with_model_offline(self):
        def offline(_):
            raise TimeoutError()

        outcomes = Counter()
        route = lambda text: classify_reply(text, "local", offline, outcomes=outcomes)
        result = run_case("P101", text="Nobody came to collect my package", reply="Please book Thursday",
                          after_booking="What time is my pickup again?", classify=route)
        self.assertEqual((result["state"], result["bookings_created"], result["confirmation_notices_delivered"]),
                         ("RESOLVED", 1, 1))
        self.assertFalse(outcomes)

    def test_read_existing_booking(self):
        outcomes = Counter()

        def route(text):
            return classify_reply(text, "local", lambda _: '{"intent":"booking_details"}', outcomes=outcomes)

        question = "Which number do I give the front desk for this appointment?"
        self.assertEqual(read_intent(question), "unknown")
        result = run_case("P101", reply="Please book Thursday", after_booking=question, classify=route)
        self.assertEqual(outcomes, {"classified": 1})
        self.assertEqual((result["state"], result["bookings_created"], result["confirmation_notices_delivered"]),
                         ("RESOLVED", 1, 1))
        self.assertIn("BK-P101", result["turns"][-1]["message"])

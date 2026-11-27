from datetime import datetime, timedelta
import unittest

from carrier import MockServices
from demo import run_case
from pickup import Case, handle


class EmailReplyTests(unittest.TestCase):
    def offer(self):
        case, services = Case("P101"), MockServices()
        handle(case, services, "", carrier_event=True)
        return case, services

    def test_accept_reply(self):
        for text in (
            "Thursday works for me!\nBest,\nAnna",
            "Please book Thursday",
            "Thursday 26 November, 12:00–16:00 CET, please.",
            "El jueves me viene bien.\nUn saludo,\nMaría López",
            "Por favor, resérvame el jueves.\nSaludos, Ana",
            "Thursday please\n\nOn Tuesday, Support wrote:\n> Did the driver come?\n> Please choose A or B.",
            "El jueves me viene bien\nEl martes, Soporte escribió:\n> ¿Te viene bien el miércoles?",
        ):
            with self.subTest(text=text):
                case, services = self.offer()
                result = handle(case, services, text, classify=self.no_model)
                self.assertEqual(result["state"], "RESOLVED")
                self.assertEqual(services.bookings[case.case_id]["slot"], "B")
                self.assertEqual(len(services.notices), 1)
                self.assertTrue(any(text in fact for fact in case.evidence))

    def test_unmarked_previous_offer(self):
        case, services = self.offer()
        message = "Please book Thursday\n\nOn Tuesday, Support wrote:\n" + case.last_reply
        self.assertEqual(handle(case, services, message)["state"], "RESOLVED")
        self.assertEqual(services.bookings[case.case_id]["slot"], "B")

    def test_consent_from_new_text_only(self):
        for text in (
            "> Thursday works for me",
            "No.\nOn Tuesday someone wrote:\n> Please book Thursday",
            "Thursday works for me,\nBest,\nAna\nP.S. the parcel has just been collected.",
            "Please book Thursday\nOn Tuesday, Support wrote:\n> Select a date\nI need to change the address.",
            "Thursday works\nOn Tuesday, Support wrote:\nI don't want this pickup.",
            "> Option B please\nCan you check whether Thursday is available?",
            "Please book Thursday if you can change the address.",
            "Please book Thursday?\nBest, Ana",
            "El jueves me viene bien\nUn saludo,\nAna\nP.D. Ya recogieron el paquete.",
            "Thursday 26 November, 15:00–18:00 CET, please.",
            "Thursday works\nBest,\nCancel",
        ):
            with self.subTest(text=text):
                case, services = self.offer()
                handle(case, services, text)
                self.assertFalse(services.bookings)
                self.assertFalse(services.notices)

    def test_reply_against_live_options(self):
        for reply, slot in (("Thu pls", "B"), ("Thrusday is good", "B"), ("the 26th works", "B"),
                            ("Fine, Thursday. But this is the last time I order from you.", "B"),
                            ("Either Wednesday or Thursday is fine.", "A")):
            with self.subTest(reply=reply):
                case, services = self.offer()
                handle(case, services, reply)
                self.assertEqual(services.bookings[case.case_id]["slot"], slot)
                self.assertEqual(len(services.notices), 1)
                self.assertFalse(services.queue)

    def test_unclear_email_keeps_original_link(self):
        for reply, expected in (("My diary's upstairs.", "Which window"), ("Sí, perfecto", "franja"),
                                ("Which one is earlier?", "earliest"), ("Is Thursday ok? What time exactly?", "Thu 26"),
                                ("Thursday doesn't work for me", "Wed 25"), ("Dijous em va bé", "enllaç"),
                                ("Jeudi me convient.", "lien")):
            with self.subTest(reply=reply):
                case, services = self.offer()
                rev = case.offer_number
                answer = handle(case, services, reply)
                self.assertIn(expected, answer["message"])
                self.assertFalse(services.queue)
                self.assertFalse(services.bookings)
                handle(case, services, "", selected_slot="B", offer_number=rev)
                self.assertEqual(services.bookings[case.case_id]["slot"], "B")

    def test_operational_update_blocks_live_link(self):
        for report in ("My parcel is with the driver now.", "They already have the return.",
                       "The carrier says it is already at the sorting centre.", "Ya está en manos del repartidor.",
                       "No collection needed. I'm taking this to the shop myself.",
                       "Thursday would be okay if you are at the new building.",
                       "Jeudi, mais le colis est déjà déposé.", "Dijous em va bé, però ja he deixat el paquet."):
            with self.subTest(report=report):
                case, services = self.offer()
                rev = case.offer_number
                handle(case, services, report)
                self.assertIn(case.case_id, services.queue)
                handle(case, services, "", selected_slot="B", offer_number=rev)
                self.assertFalse(services.bookings)
                self.assertFalse(services.notices)

    def test_both_days_accepted_after_first_cutoff(self):
        for timer in (False, True):
            with self.subTest(timer=timer):
                case, services = self.offer()
                services.now += timedelta(hours=20)
                if timer:
                    handle(case, services, "")
                handle(case, services, "Either Wednesday or Thursday works.")
                self.assertEqual(services.bookings[case.case_id]["slot"], "B")
                self.assertFalse(services.queue)

    def test_reply_after_booking(self):
        for text, review in (("Thnaks, that helps!", False), ("Cheers, that's brilliant", False),
                             ("Could you reschedule?", True), ("The courier never showed up again.", True)):
            with self.subTest(text=text):
                case, services = self.offer()
                handle(case, services, "Thursday works for me")
                finished = case.resolved_at
                handle(case, services, text)
                self.assertEqual(bool(services.queue), review)
                if not review:
                    self.assertEqual(case.resolved_at, finished)
                self.assertEqual((len(services.bookings), len(services.notices)), (1, 1))

    @staticmethod
    def no_model(text):
        raise AssertionError(f"Unexpected model call for {text!r}")

    def test_read_existing_booking(self):
        for message in (
            "Got it, thank you!", "Perfect, see you then!", "Gracias por la ayuda.",
            "What time is my pickup again?", "What is my booking reference?",
            "Is my Thursday pickup confirmed?", "¿A qué hora es mi recogida?",
            "¿Cuál es la referencia de mi reserva?\nSaludos,\nAna",
        ):
            with self.subTest(message=message):
                case, services = self.offer()
                handle(case, services, "Thursday works for me!", classify=self.no_model)
                before = len(services.calls)
                resolved = case.resolved_at
                result = handle(case, services, message, classify=self.no_model)
                self.assertEqual(result["state"], "RESOLVED")
                self.assertEqual(case.resolved_at, resolved)
                self.assertIn("BK-P101", result["message"])
                self.assertIn("12:00–16:00", result["message"])
                self.assertFalse(services.queue)
                self.assertEqual([c["tool"] for c in services.calls[before:]],
                                 ["carrier.lookup", "support.check_booking_receipt"])

    def test_model_read_has_no_booking_authority(self):
        case, services = self.offer()
        handle(case, services, "Please book Thursday", classify=self.no_model)
        answer = handle(case, services, "Can you remind me of the appointment window?",
                        classify=lambda text: "booking_details")
        self.assertEqual(answer["state"], "RESOLVED")
        self.assertIn("BK-P101", answer["message"])
        for message in (
            "Could you remind me of the time and move it to Friday?",
            "What if I need to change the address?",
            "Can you tell me the booking time? My plans have changed.",
            "What about the extra fee for this visit?",
        ):
            with self.subTest(message=message):
                case, services = self.offer()
                handle(case, services, "Please book Thursday")
                self.assertEqual(handle(case, services, message, classify=lambda _: "booking_details")["state"],
                                 "HUMAN_REVIEW")
                self.assertEqual(len(services.bookings), 1)

    def test_confirmation_uses_current_evidence(self):
        for change in ("cancelled", "wrong_receipt", "no_notice", "past", "collected"):
            with self.subTest(change=change):
                case, services = self.offer()
                handle(case, services, "Please book Thursday")
                if change == "wrong_receipt":
                    services.bookings[case.case_id]["reference"] = "unrelated"
                elif change == "no_notice":
                    services.notices.clear()
                elif change == "past":
                    services.now = datetime.fromisoformat(case.accepted_end) + timedelta(minutes=1)
                else:
                    services.cases[case.case_id]["status"] = change
                before = len(services.calls)
                result = handle(case, services, "What time is my pickup again?")
                if change == "past":
                    self.assertIn("don't have a collection scan", result["message"])
                elif change == "collected":
                    self.assertIn("reported collecting", result["message"])
                else:
                    self.assertEqual(result["state"], "HUMAN_REVIEW")
                self.assertNotIn("is confirmed for", result["message"])
                actions = [c["tool"] for c in services.calls[before:]]
                self.assertNotIn("carrier.book_once", actions)
                self.assertNotIn("support.notify", actions)

    def test_help_contacts_after_confirmation(self):
        for message, contacts in (("Got it, thank you!", 1), ("What is my booking reference?", 2)):
            with self.subTest(message=message):
                result = run_case("P101", reply="Please book Thursday\nBest, Ana", after_booking=message)
                self.assertEqual(result["shopper_help_contacts"], contacts)
                self.assertEqual(result["state"], "RESOLVED")


if __name__ == "__main__":
    unittest.main()

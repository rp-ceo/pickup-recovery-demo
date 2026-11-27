import unittest

from carrier import MockServices
from pickup import Case, handle


class ChoiceReplyTests(unittest.TestCase):
    def start(self, revised=False):
        case, services = Case("P101"), MockServices()
        handle(case, services, "", carrier_event=True)
        if revised:
            services.cases[case.case_id]["slots"] = ["B"]
            handle(case, services, "", carrier_event=True)
        return case, services

    def test_questions_need_consent(self):
        for text in ("Thursday?", "Thursday?!", "Option B?!", "¿Jueves?!", "¿Jueves", "B/1？", "Thursday? Thanks!",
                     "Gracias, ¿jueves?!", "Could you do Thursday instead?", "¿Está disponible el jueves?",
                     "Thanks, Thursday?!", "Option B?\nSent from my iPhone"):
            with self.subTest(text=text):
                case, services = self.start()
                result = handle(case, services, text)
                self.assertEqual(result["state"], "OFFERED")
                self.assertIn("B", result["message"])
                self.assertFalse(services.queue)
                self.assertFalse(services.bookings)
                self.assertFalse(services.notices)
                result = handle(case, services, "Yes, Thursday please")
                self.assertEqual(result["state"], "RESOLVED")
                self.assertEqual(services.bookings[case.case_id]["slot"], "B")

    def test_revised_code_requires_consent(self):
        case, services = self.start(revised=True)
        for text in ("B/2?!", "¿Opción B/2?", "B/2?", "Thanks, B/1", "Thursday works"):
            self.assertIn("B/2", handle(case, services, text)["message"])
            self.assertFalse(services.bookings)
            self.assertFalse(services.notices)
        self.assertEqual(handle(case, services, "Yes, B/2 please")["state"], "RESOLVED")
        self.assertEqual(len(services.notices), 1)

    def test_email_acceptance(self):
        for text in ("Thanks, Thursday works for me!", "Yes, Thursday works for me.", "Yes, Thursday please",
                     "Thursday afternoon would be perfect for me.", "I can do Thursday",
                     "Thursday works for me.\r\n\r\nSent from my iPhone",
                     "Me va bien el jueves", "Sí, el jueves por la tarde me viene bien, gracias.",
                     "Gracias, me viene bien el jueves.\nEnviado desde mi iPhone"):
            with self.subTest(text=text):
                case, services = self.start()
                self.assertEqual(handle(case, services, text)["state"], "RESOLVED")
                self.assertEqual(services.bookings[case.case_id]["slot"], "B")
                self.assertEqual(len(services.notices), 1)

    def test_mixed_email(self):
        for text in ("Thursday works for me.\nSent from my iPhone\nWait, the carrier just picked it up.",
                     "Thanks, Thursday works if the fee is waived.", "Si el jueves me va bien, te aviso.",
                     "Thursday works for me or Wednesday works too.", "I can do Thursday morning."):
            with self.subTest(text=text):
                case, services = self.start()
                handle(case, services, text)
                self.assertFalse(services.bookings)
                self.assertFalse(services.notices)

    def test_spanish_thanks_after_booking(self):
        for weekday, state in (("jueves", "RESOLVED"), ("miércoles", "HUMAN_REVIEW")):
            with self.subTest(weekday=weekday):
                case, services = self.start()
                handle(case, services, "Me va bien el jueves")
                result = handle(case, services, f"¡Gracias, nos vemos el {weekday}!")
                self.assertEqual(result["state"], state)
                self.assertEqual(len(services.queue), int(state == "HUMAN_REVIEW"))
                self.assertEqual((len(services.bookings), len(services.notices)), (1, 1))


if __name__ == "__main__":
    unittest.main()

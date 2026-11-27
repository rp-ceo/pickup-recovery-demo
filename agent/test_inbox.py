import unittest
from datetime import timedelta

from carrier import MockServices
from demo import run_case
from pickup import Case, handle


class InboxTests(unittest.TestCase):
    def open_offer(self, case_id="P101"):
        tools, case = MockServices(), Case(case_id)
        handle(case, tools, tools.cases[case_id]["sample"])
        return case, tools

    def test_reply_by_email(self):
        for reply in ("Thursday works for me", "Option B please", "The second one"):
            with self.subTest(reply=reply):
                result = run_case("P101", reply=reply)
                self.assertEqual(result["state"], "RESOLVED")
                self.assertIn("Thu 26 Nov, 12:00–16:00 CET", result["turns"][-1]["message"])
                self.assertEqual(result["bookings_created"], 1)

    def test_availability_questions(self):
        for reply in ("Wednesday?", "Can you check if Thursday is available?",
                      "Either Wednesday or Thursday might work, can you check?"):
            with self.subTest(reply=reply):
                case, tools = self.open_offer()
                answer = handle(case, tools, reply)
                self.assertEqual(answer["state"], "OFFERED")
                self.assertIn("Thu 26", answer["message"])
                self.assertFalse(tools.bookings)
                self.assertFalse(tools.queue)

    def test_conditional_fee(self):
        case, tools = self.open_offer()
        handle(case, tools, "Thursday works if there is no charge. Can you check?")
        self.assertEqual(tools.queue[case.case_id]["owner"], "Merchant Operations")
        self.assertFalse(tools.bookings)

    def test_ambiguous_weekday(self):
        tools, case = MockServices(), Case("P101")
        tools.slot_starts["B"] = tools.slot_starts["A"] + timedelta(hours=4)
        tools.slots["B"] = "Wed 25 Nov, 12:00–16:00 CET"
        handle(case, tools, tools.cases["P101"]["sample"])
        handle(case, tools, "Wednesday works")
        self.assertEqual(case.state, "OFFERED")
        self.assertFalse(tools.bookings)
        handle(case, tools, "Wednesday afternoon")
        self.assertEqual(tools.bookings["P101"]["slot"], "B")

    def test_revised_email_offer(self):
        case, tools = self.open_offer()
        tools.cases["P101"]["slots"] = ["B"]
        handle(case, tools, "", carrier_event=True)
        for stale in ("B", "B/1"):
            result = handle(case, tools, stale)
            self.assertIn("B/2", result["message"])
            self.assertFalse(tools.bookings)
        result = handle(case, tools, "B/2", message_id="reply")
        self.assertEqual(result["state"], "RESOLVED")
        handle(case, tools, "B/2", message_id="reply")
        self.assertEqual((len(tools.bookings), len(tools.notices)), (1, 1))

    def test_old_button_after_email(self):
        result = run_case("P101", reply="I prefer the second one.", slot="A")
        self.assertEqual(result["state"], "RESOLVED")
        self.assertIn("Thu", result["turns"][-1]["message"])
        self.assertEqual(result["bookings_created"], 1)
        self.assertEqual(result["confirmation_notices_delivered"], 1)

    def test_thank_you_and_amendment(self):
        case, tools = self.open_offer()
        handle(case, tools, "Option A please")
        handle(case, tools, "Great, see you Wednesday!")
        self.assertEqual(case.state, "RESOLVED")
        self.assertFalse(tools.queue)
        result = handle(case, tools, "Actually can you move it to Thursday?")
        self.assertEqual(result["state"], "HUMAN_REVIEW")
        self.assertIn("stays in place", result["message"])
        self.assertIn("Thursday", tools.queue["P101"]["next_step"])
        self.assertEqual((len(tools.bookings), len(tools.notices)), (1, 1))

    def test_collected_parcel(self):
        for text in ("The courier did come and collect it, thanks", "Somebody else collected it.",
                     "Did the courier collect it?", "Was the parcel collected already?"):
            with self.subTest(text=text):
                result = run_case("P101", text=text, slot="B") if "?" not in text else run_case("P101", text=text)
                self.assertFalse(result["bookings_created"])
                self.assertNotEqual(result["state"], "OFFERED")

    def test_frustrated_shopper(self):
        result = run_case("P131", scripted=True)
        self.assertEqual(result["state"], "OFFERED")
        self.assertIn("day of work", result["turns"][0]["message"])
        self.assertFalse(result["bookings_created"])
        question = run_case("P102", text="This is ridiculous, I took a day off work")
        self.assertEqual(question["state"], "WAITING_CARRIER")

    def test_spanish_pickup(self):
        for source in ("El mensajero no vino", "Nadie vino a recoger mi devolución."):
            with self.subTest(source=source):
                result = run_case("P101", text=source, reply="El jueves me va bien")
                self.assertIn("Responde", result["turns"][0]["message"])
                self.assertIn("Tu nueva recogida", result["turns"][-1]["message"])
                self.assertEqual(result["confirmation_notices_delivered"], 1)
        for text in ("No estoy seguro si ya lo recogió el mensajero", "Quiero cancelar la recogida",
                     "Ya lo recogió el mensajero ayer", "¿Me van a cobrar otra recogida?"):
            result = run_case("P101", text=text)
            self.assertFalse(result["bookings_created"])
            self.assertNotEqual(result["state"], "OFFERED")

    def test_spanish_booking_change(self):
        for key, status in (("P107", "podría seguir en pie"), ("P101", "sigue en pie"),
                            ("P132", "podría seguir en pie")):
            with self.subTest(case=key):
                case, tools = self.open_offer(key)
                handle(case, tools, "Option A please")
                result = handle(case, tools, "¿Puedes mover la recogida al jueves?")
                self.assertIn("mié 25 nov, 08:00–12:00 CET", result["message"])
                self.assertIn("jueves", result["message"])
                self.assertIn(status, result["message"])
                self.assertEqual(len(tools.bookings), 1)
                self.assertEqual(len(tools.notices), int(key == "P101"))

    def test_spanish_repeat_charge(self):
        result = run_case("P134", text="El mensajero no vino.")
        self.assertEqual(result["owner"], "Merchant Operations")
        self.assertIn("quién cubrirá el coste", result["turns"][0]["message"])
        self.assertFalse(result["bookings_created"])

    def test_withdraw_return(self):
        messages = (
            "El mensajero no vino. Ya no quiero devolverlo.", "Me lo quedo.",
            "Ya no hace falta que vengan.", "No quiero que lo recojan.",
            "I no longer want to return it.",
        )
        for text in messages:
            for has_offer in (True, False):
                with self.subTest(text=text, has_offer=has_offer):
                    tools, case = MockServices(), Case("P101")
                    if has_offer:
                        handle(case, tools, "El mensajero no vino")
                    handle(case, tools, text)
                    result = handle(case, tools, "", selected_slot="A", offer_number=1)
                    self.assertEqual(result["state"], "HUMAN_REVIEW")
                    self.assertFalse(tools.bookings)
                    self.assertFalse(tools.notices)
        result = run_case("P101", text="No quiero cancelar. El mensajero no vino.")
        self.assertEqual(result["state"], "OFFERED")

    def test_timeout_without_lookup(self):
        result = run_case("P107", scripted=True)
        self.assertEqual(result["state"], "HUMAN_REVIEW")
        self.assertEqual(result["confirmation_notices_delivered"], 0)
        tools = [call["tool"] for turn in result["turns"] for call in turn["tool_calls"]]
        self.assertEqual(tools.count("carrier.book_once"), 1)
        self.assertNotIn("carrier.find_by_attempt", tools)
        pending = run_case("P114", scripted=True)
        self.assertIn("may still go ahead", pending["turns"][-1]["message"])
        self.assertIn("Thursday", pending["next_step"])

    def test_window_end_update(self):
        result = run_case("P112", scripted=True)
        turns = result["turns"]
        self.assertEqual([turn["state"] for turn in turns], ["WINDOW_OPEN", "WAITING_CARRIER", "HUMAN_REVIEW"])
        self.assertIn("16:30 CET", turns[1]["message"])
        calls = [call["tool"] for turn in turns for call in turn["tool_calls"]]
        self.assertEqual(calls.count("support.send_window_update"), 1)
        self.assertEqual(calls.count("support.send_inquiry_update"), 1)
        self.assertEqual(result["bookings_created"], 0)

    def test_undelivered_window_update(self):
        tools, case = MockServices(), Case("P112")
        record = tools.cases["P112"]
        record["window_update_fails"] = True
        handle(case, tools, record["sample"])
        tools.now += timedelta(days=1)
        handle(case, tools, "")
        self.assertEqual(case.state, "HUMAN_REVIEW")
        self.assertIn("reach the shopper", tools.queue["P112"]["next_step"])

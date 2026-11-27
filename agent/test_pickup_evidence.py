import unittest

from carrier import MockServices
from intent import read_intent
from pickup import Case, handle


class PickupEvidenceTests(unittest.TestCase):
    def check_hold(self, message, reason):
        for has_offer in (False, True):
            with self.subTest(message=message, has_offer=has_offer):
                case, services = Case("P101"), MockServices()
                if has_offer:
                    handle(case, services, "", carrier_event=True)
                offer = case.offer_number
                response = handle(case, services, message, message_id="report")
                self.assertEqual(response["state"], "HUMAN_REVIEW")
                self.assertEqual(services.queue["P101"]["reason"], reason)
                self.assertFalse(case.offered)
                self.assertTrue(any(message in row for row in response["evidence"]))
                handle(case, services, "", selected_slot="A", offer_number=offer)
                handle(case, services, "Thursday works for me", message_id="reply")
                self.assertFalse(services.bookings)
                self.assertFalse(services.notices)

    def test_handover(self):
        for message in (
            "The courier finally showed up and took my parcel.",
            "This is ridiculous, the courier came after all and now has my parcel.",
            "Someone showed up this morning and picked it up.",
            "I already posted it after the pickup failed.",
            "My wife handed him the parcel.",
            "No vino nadie, pero al final lo dejé en un punto de recogida.",
            "Ya entregué el paquete al mensajero.",
            "Jueves, thanks. The driver just picked the box up.",
        ):
            self.check_hold(message, "Shopper reports collection")

    def test_partial_collection(self):
        self.check_hold("I have two returns and the driver only picked up one of them.", "Partial collection")

    def test_shopper_has_nothing_to_return(self):
        self.check_hold("This is ridiculous, I no longer have anything to return.", "Pickup declined")

    def test_repeat_visits(self):
        for message in (
            "Two days in a row the courier didn't turn up. I'm furious.",
            "I've stayed home twice now and nobody showed up either time.",
            "The driver didn't come yesterday or today.",
            "The courier missed both appointments.",
            "Both appointments were missed.",
            "Both times I waited at home; nobody came.",
            "The courier never came on either occasion.",
            "En las dos ocasiones me quedé en casa y nadie vino.",
            "The courier missed both of our visits.",
            "El repartidor no vino a ninguna de las dos citas.",
            "The courier didn't show up on Monday or on Wednesday.",
            "Nadie vino ayer ni hoy.",
            "Dos días seguidos en casa y el mensajero no llegó.",
        ):
            self.check_hold(message, "Repeated shopper misses")

    def test_changed_facts_after_miss(self):
        for message in (
            "The pickup failed yesterday but I left it with the shop today.",
            "Nobody came, but later the courier took my bag.",
            "The driver didn't show up. Since then I've shipped the parcel myself.",
            "Nadie vino, pero acabé llevándolo a Correos.",
            "Nobody came on Tuesday, but the box is with the neighbour's driver now.",
            "Nobody came. Can you rebook? Since then we got a second label.",
        ):
            self.check_hold(message, "New pickup details")

    def test_unrecognised_followup(self):
        case, services = Case("P101"), MockServices()
        handle(case, services, "", carrier_event=True)
        handle(case, services, "I'm furious and something just happened to the box.")
        handle(case, services, "", selected_slot="A", offer_number=1)
        self.assertEqual(case.state, "HUMAN_REVIEW")
        self.assertFalse(services.bookings)

    def test_single_miss(self):
        for message in (
            "The courier never took my parcel.",
            "Nobody came, but I still have my parcel. Could we book another pickup?",
            "Nadie vino, pero el paquete sigue conmigo. ¿Podemos reservar otra recogida?",
            "I called twice and the courier didn't show up.",
            "I just took one day off and the courier never showed up.",
            "Nobody came for my pickup. I never handed the parcel over.",
            "Llamé dos veces pero el mensajero no vino.",
            "No dejé el paquete en un punto de recogida, el mensajero no vino.",
        ):
            with self.subTest(message=message):
                case, services = Case("P101"), MockServices()
                self.assertEqual(handle(case, services, message)["state"], "OFFERED")
                self.assertFalse(services.bookings)
        self.assertEqual(read_intent("I don't think she took the parcel."), "unknown")
        self.assertEqual(read_intent("What if they collected the parcel?"), "unknown")

import unittest
from datetime import timedelta

from carrier import IncompleteCarrierRecord, MockServices
from demo import run_case
from intent import read_intent
from pickup import Case, handle


class CustodyTests(unittest.TestCase):
    def test_shopper_drop_off(self):
        for report in (
            "It's at the post office now because the driver never came.",
            "I took my parcel to the depot as the courier never came.",
            "I left it with the parcel shop because nobody came.",
            "Nobody came, so I left it with the parcel shop.",
            "I gave it to the shop assistant because nobody came.",
            "The driver never came. My package is at the parcel shop now.",
            "Ya lo llevé al punto de entrega porque el mensajero no vino.",
            "El mensajero no vino, así que llevé el paquete a Correos.",
            "Se lo di al dependiente porque el mensajero no vino.",
            "El mensajero no vino, así que se lo di al dependiente.",
            "Le entregué la caja a la encargada porque nadie vino.",
            "El mensajero vino por una de las dos cajas. La otra sigue aquí.",
            "La otra sigue aquí. El mensajero vino por una de las dos cajas.",
            "El repartidor retiró uno de mis tres paquetes.",
            "I handed the first one to the courier but the second one is still here.",
            "Le entregué el primer paquete al repartidor. El segundo sigue aquí.",
            "The other parcel is still at home, but I gave the courier the first one.",
        ):
            for has_offer in (False, True):
                with self.subTest(report=report, has_offer=has_offer):
                    case, services = Case("P101"), MockServices()
                    if has_offer:
                        handle(case, services, "", carrier_event=True)
                    handle(case, services, report, message_id="report")
                    self.assertEqual(case.state, "HUMAN_REVIEW")
                    handle(case, services, "B", message_id="follow-up")
                    handle(case, services, "", selected_slot="B", offer_number=1)
                    self.assertFalse(case.offered)
                    self.assertFalse(services.bookings)
                    self.assertFalse(services.notices)

    def test_unresolved_custody_before_miss(self):
        for report in (
            "My package is with someone else now because nobody came.",
            "También envié la caja por otra vía porque el mensajero no vino.",
            "Since the driver never came, my neighbour took the parcel somewhere.",
        ):
            with self.subTest(report=report):
                result = run_case("P101", text=report, reply="B")
                self.assertEqual(result["state"], "HUMAN_REVIEW")
                self.assertEqual(result["bookings_created"], 0)

    def test_shopper_still_has_parcel(self):
        for report in (
            "It isn't at the post office. I still have it because the courier never came.",
            "I didn't take it to the post office; the driver never came.",
            "I didn't leave it with the parcel shop. Nobody came.",
            "Nobody came. I didn't leave it with the shop assistant.",
            "No se lo di al dependiente porque el mensajero no vino.",
            "El mensajero no vino. No se lo di al dependiente.",
            "No lo llevé al punto de entrega, el mensajero no vino.",
            "El paquete no está en Correos. El mensajero no vino.",
            "Yo no lo llevé a Correos, el mensajero no vino.",
            "Es la segunda vez que escribo, pero el mensajero no vino.",
        ):
            with self.subTest(report=report):
                self.assertNotIn(read_intent(report), {"already_collected", "partial_collection"})
                self.assertEqual(run_case("P101", text=report)["state"], "OFFERED")

    def test_scan_blocks_booking(self):
        for phase in ("before offer", "before choice", "at booking"):
            with self.subTest(phase=phase):
                case, services = Case("P101"), MockServices()
                record = services.cases[case.case_id]
                if phase != "before offer":
                    handle(case, services, "", carrier_event=True)
                record["collected_at"] = (services.now - timedelta(minutes=18)).isoformat()
                if phase == "at booking":
                    with self.assertRaises(IncompleteCarrierRecord):
                        services.book_once(case.case_id, "B", case.offered["B"], case.offered_starts["B"],
                                           case.offered_ends["B"])
                else:
                    handle(case, services, "B" if phase == "before choice" else record["sample"])
                    self.assertEqual(case.state, "HUMAN_REVIEW")
                    self.assertTrue(any("collection" in fact for fact in case.evidence))
                    handle(case, services, "", selected_slot="B", offer_number=1)
                self.assertFalse(services.bookings)
                self.assertFalse(services.notices)

    def test_second_miss_in_spanish(self):
        for text in (
            "Ya es la segunda vez que no viene nadie. Estoy harto.",
            "Nadie viene por segunda vez y estoy harta.",
            "Es la tercera vez que no se presenta nadie.",
        ):
            with self.subTest(text=text):
                result = run_case("P101", text=text, slot="B")
                self.assertEqual(result["state"], "HUMAN_REVIEW")
                self.assertIn("Soporte", result["turns"][0]["message"])
                self.assertEqual(result["bookings_created"], 0)

    def test_no_carrier_response(self):
        result = run_case("P102", advance_minutes=30)
        self.assertEqual(result["owner"], "Support Operations")
        self.assertIn("Support", result["turns"][-1]["message"])
        self.assertIn("update you", result["turns"][-1]["message"])

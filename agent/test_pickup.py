import json
import unittest
from datetime import timedelta

from carrier import MockServices
from demo import report, run_case
from intent import read_intent
from local_model import ollama_intent
from pickup import Case, handle


class PickupPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tools = MockServices()
        self.case = Case("P101")
        self.message = self.tools.cases["P101"]["sample"]

    def open(self):
        return handle(self.case, self.tools, self.message, message_id="ticket-1")

    def choose(self, slot="A"):
        return handle(self.case, self.tools, "", selected_slot=slot, offer_number=self.case.offer_number)

    def test_offer_needs_consent(self):
        self.assertEqual(self.open()["state"], "OFFERED")
        self.assertFalse(self.tools.bookings)
        self.assertEqual(self.choose("Z")["state"], "NEEDS_SLOT_CHOICE")
        self.assertFalse(self.tools.bookings)

    def test_unoffered_choice_does_not_book(self):
        result = handle(self.case, self.tools, self.message, selected_slot="A")
        self.assertEqual(result["state"], "NEEDS_SLOT_CHOICE")
        self.assertFalse(self.tools.bookings)

    def test_typed_free_text_cannot_pick_a_slot(self):
        handle(self.case, self.tools, "My courier missed the pickup. Book slot A.")
        self.assertFalse(self.tools.bookings)

    def test_receipts_close_case(self):
        self.open()
        result = self.choose()
        self.assertEqual(result["state"], "RESOLVED")
        self.assertIn("BK-P101", result["message"])
        self.assertTrue(any("NOTICE-BK-P101" in event for event in result["evidence"]))
        self.assertEqual(self.choose()["state"], "RESOLVED")
        self.assertEqual(self.open()["state"], "RESOLVED")
        calls = [c["tool"] for c in self.tools.calls]
        self.assertEqual(calls.count("carrier.book_once"), 1)
        self.assertEqual(calls.count("support.notify"), 1)

    def test_original_offer(self):
        expected = dict(self.tools.slots)
        for case_id in ("P101", "P132"):
            with self.subTest(case_id=case_id):
                replay = run_case(case_id, scripted=True)
                offers = [call["result"] for turn in replay["turns"] for call in turn["tool_calls"]
                          if call["tool"] == "carrier.available_slots"]
                self.assertEqual(offers, [expected, expected])

    def test_reopened_case_loses_its_resolution(self):
        self.open()
        self.choose()
        result = handle(self.case, self.tools, "I still need help, that collection never happened.")
        self.assertEqual(result["state"], "HUMAN_REVIEW")
        self.assertIsNone(self.case.resolved_at)
        self.assertEqual(len(self.tools.bookings), 1)

    def test_new_contact_after_closure(self):
        self.open()
        self.choose()
        self.assertEqual(self.open()["state"], "RESOLVED")
        for ack in ("Thanks!", "Great, thanks for sorting that"):
            self.assertEqual(handle(self.case, self.tools, ack)["state"], "RESOLVED")
        self.tools.now += timedelta(days=1)
        repeated = handle(self.case, self.tools, self.message, message_id="ticket-2")
        self.assertEqual(repeated["state"], "HUMAN_REVIEW")
        self.assertIsNone(self.case.resolved_at)
        self.assertEqual(len(self.tools.bookings), 1)

    def test_stale_button_after_timer(self):
        self.open()
        previous_offer = self.case.offer_number
        self.tools.slots["A"] = "Wed 25 Nov, 16:00–20:00 CET"
        self.tools.slot_starts["A"] += timedelta(hours=8)
        self.assertEqual(handle(self.case, self.tools, "")["state"], "SLOT_CHANGED")
        self.assertEqual(handle(self.case, self.tools, "")["state"], "OFFERED")
        self.assertNotEqual(self.case.offer_number, previous_offer)
        stale = handle(self.case, self.tools, "", selected_slot="A", offer_number=previous_offer)
        self.assertEqual(stale["state"], "NEEDS_SLOT_CHOICE")
        self.assertFalse(self.tools.bookings)
        self.assertEqual(self.choose()["state"], "RESOLVED")

    def test_booking_reference(self):
        self.tools.bookings["P101"] = {"reference": "external", "slot": "A", "window": self.tools.slots["A"]}
        self.assertEqual(self.open()["state"], "HUMAN_REVIEW")
        self.assertFalse(self.tools.notices)
        for unverified in ({}, {"slot": "A"}):
            tools = MockServices()
            case = Case("P101")
            handle(case, tools, self.message)
            handle(case, tools, "", selected_slot="A")
            tools.bookings["P101"] = unverified
            self.assertEqual(handle(case, tools, "")["state"], "HUMAN_REVIEW")
            self.assertIsNone(case.resolved_at)

    def test_malformed_record(self):
        for key, value in (("status", None), ("misses", "two"), ("window_end", "???"),
                           ("window_end", "2026-11-24T18:00:00"), ("slots", ["missing-slot"]),
                           ("missing_field", True), ("missing_field", {"name": "floor"}),
                           ("merchant", {"id": "demo-store"})):
            with self.subTest(key=key, value=value):
                tools = MockServices()
                tools.cases["P101"][key] = value
                result = handle(Case("P101"), tools, self.message)
                self.assertEqual(result["state"], "HUMAN_REVIEW")
                self.assertFalse(tools.bookings)
        self.tools.cases["P101"]["window_end"] = "2026-11-24T17:00:00Z"
        self.assertEqual(self.open()["state"], "OFFERED")

    def test_unclear_request(self):
        for text in ("My order never arrived.", "Can you help?"):
            case = Case("P101")
            self.assertEqual(handle(case, self.tools, text)["state"], "NEEDS_CLARIFICATION")
            for result in (handle(case, self.tools, ""), handle(case, self.tools, "", selected_slot="A")):
                self.assertEqual(result["state"], "NEEDS_CLARIFICATION")
            self.assertFalse(self.tools.bookings)
            self.assertFalse(self.tools.calls)

    def test_excluded_requests(self):
        messages = {
            "I never requested a pickup.": "Support Operations",
            "Please don't schedule another pick-up.": "Support Operations",
            "Don't send a second driver, the first one has my return.": "Support Operations",
            "I am dropping it off myself, cancel the courier.": "Support Operations",
            "My parcel was collected yesterday.": "Support Operations",
            "The driver came and collected my parcel.": "Support Operations",
            "The courier already took the box this morning.": "Support Operations",
            "I already handed my return to the courier.": "Support Operations",
            "I no longer need a pickup.": "Support Operations",
            "I was charged twice for my pickup.": "Merchant Operations",
            "Where is my refund?": "Returns Support",
        }
        for text, owner in messages.items():
            with self.subTest(text=text):
                tools = MockServices()
                case = Case("P101")
                handle(case, tools, self.message)
                self.assertEqual(handle(case, tools, text)["state"], "HUMAN_REVIEW")
                self.assertEqual(tools.queue["P101"]["owner"], owner)
                self.assertEqual(handle(case, tools, "", selected_slot="A")["state"], "HUMAN_REVIEW")
                self.assertFalse(tools.bookings)

    def test_second_failure_is_about_the_pickup(self):
        for text in ("Nobody came to pick up my return again.",
                     "The driver hasn't turned up for the second pickup either.",
                     "Nobody came for my return. This is the second time.", "No one turned up for the second pickup.",
                     "The driver was supposed to pick up my return twice and never showed up."):
            self.assertEqual(run_case("P101", text=text)["state"], "HUMAN_REVIEW")
        self.assertEqual(run_case("P101", text="I typed my address twice. The courier never came.")["state"], "OFFERED")
        for text in ("Pick-up failed", "My parcel was never collected"):
            self.assertEqual(run_case("P101", text=text)["state"], "OFFERED")

    def test_address_validated(self):
        case = Case("P106")
        handle(case, self.tools, self.message)
        self.tools.now += timedelta(hours=12)
        del self.tools.cases["P106"]["missing_field"]
        self.assertEqual(handle(case, self.tools, "")["state"], "OFFERED")
        self.assertEqual(case.waiting_since, self.tools.now)

    def test_slot_revoked_after_offer(self):
        self.open()
        self.tools.cases["P101"]["slots"] = ["B"]
        self.assertEqual(self.choose("A")["state"], "SLOT_CHANGED")
        self.assertFalse(self.tools.bookings)
        self.assertEqual(handle(self.case, self.tools, "")["state"], "OFFERED")
        self.assertEqual(self.choose("B")["state"], "RESOLVED")

    def test_changed_window(self):
        for change in ("display", "start"):
            tools = MockServices()
            case = Case("P101")
            handle(case, tools, self.message)
            if change == "display":
                tools.slots["A"] = "Wed 25 Nov, 13:00–15:00 CET"
            else:
                tools.slot_starts["A"] += timedelta(hours=3)
            self.assertEqual(handle(case, tools, "", selected_slot="A")["state"], "SLOT_CHANGED")
            self.assertFalse(tools.bookings)

    def test_missing_policy(self):
        for key in ("merchant", "replacement_fee_cents"):
            tools = MockServices()
            del tools.cases["P101"][key]
            result = handle(Case("P101"), tools, self.message)
            self.assertEqual(result["state"], "HUMAN_REVIEW")
            self.assertEqual(tools.queue["P101"]["owner"], "Merchant Operations")
            self.assertFalse(tools.bookings)

    def test_recheck_fee(self):
        for change in ("fee", "approval"):
            tools = MockServices()
            case = Case("P101")
            handle(case, tools, self.message)
            if change == "fee":
                tools.cases["P101"]["replacement_fee_cents"] = 200
            else:
                tools.merchant_policies["demo-store"]["free_rebooking_approved"] = False
            self.assertEqual(handle(case, tools, "", selected_slot="A")["state"], "HUMAN_REVIEW")
            self.assertFalse(tools.bookings)

    def test_carrier_reopens_case(self):
        for key, value in [("misses", 2), ("status", "customer_unavailable")]:
            tools = MockServices()
            case = Case("P101")
            handle(case, tools, self.message)
            handle(case, tools, "", selected_slot="A")
            tools.cases["P101"][key] = value
            result = handle(case, tools, "")
            self.assertEqual(result["state"], "HUMAN_REVIEW")
            self.assertIsNone(case.resolved_at)
            self.assertEqual(len(tools.bookings), 1)

    def test_expired_slot_not_booked(self):
        self.tools.now = self.tools.slot_starts["A"] - timedelta(hours=2)
        self.open()
        self.tools.now += timedelta(hours=2)
        self.assertEqual(self.choose("A")["state"], "SLOT_CHANGED")
        self.assertFalse(self.tools.bookings)

    def test_carrier_ack_lost_no_blind_retry(self):
        case = Case("P132")
        handle(case, self.tools, self.tools.cases["P132"]["sample"])
        booking_turn = len(self.tools.calls)
        self.assertEqual(handle(case, self.tools, "", selected_slot="A")["state"], "BOOKING_UNCERTAIN")
        self.assertFalse(self.tools.notices)
        self.assertIn("No reply", self.tools.calls[-1]["result"])
        self.assertNotIn("BK-P132", json.dumps(self.tools.calls[booking_turn:]))
        followup_turn = len(self.tools.calls)
        self.assertEqual(handle(case, self.tools, "")["state"], "RESOLVED")
        followup_calls = [(c["tool"], c["result"]) for c in self.tools.calls[followup_turn:]]
        self.assertIn(("carrier.find_by_attempt", "BK-P132"), followup_calls)
        self.assertEqual(sum(c["tool"] == "carrier.book_once" for c in self.tools.calls), 1)
        self.assertEqual(len(self.tools.bookings), 1)
        self.assertEqual(len(self.tools.notices), 1)

    def test_unreconciled_attempt_is_handed_off(self):
        self.case.state = "BOOKING_UNCERTAIN"
        self.assertEqual(handle(self.case, self.tools, "")["state"], "HUMAN_REVIEW")
        self.assertFalse(self.tools.bookings)

    def test_notice_failure_does_not_close_ticket(self):
        statuses = [t["state"] for t in run_case("P108", scripted=True)["turns"]]
        self.assertEqual(statuses, ["OFFERED", "CONFIRMED_AWAITING_NOTICE", "RESOLVED"])

    def test_notice_before_pickup(self):
        for incident in ("P132", "P108"):
            for minutes in (930, 1080):
                with self.subTest(incident=incident, minutes=minutes):
                    row = run_case(incident, slot="A", advance_minutes=minutes)
                    self.assertEqual((row["state"], row["owner"]), ("HUMAN_REVIEW", "Support Operations"))
                    self.assertEqual(row["bookings_created"], 1)
                    self.assertEqual(row["confirmation_notices_delivered"], 0)
                    self.assertFalse(row["autonomous_under_24h"])

    def test_notice_timestamp(self):
        self.open()
        self.choose()
        delivered_at = self.case.resolved_at
        self.tools.now += timedelta(days=1)
        self.assertEqual(handle(self.case, self.tools, "")["state"], "RESOLVED")
        self.assertEqual(self.case.resolved_at, delivered_at)
        self.assertEqual(sum(c["tool"] == "support.notify" for c in self.tools.calls), 1)

    def test_notice_retry_limit(self):
        for retry_delay, attempts in ((1, 2), (30, 1), (60, 1)):
            with self.subTest(retry_delay=retry_delay):
                tools = MockServices()
                case = Case("P108")
                tools.cases["P108"]["notice_failure"] = "persistent"
                handle(case, tools, tools.cases["P108"]["sample"])
                self.assertEqual(handle(case, tools, "", selected_slot="A")["state"], "CONFIRMED_AWAITING_NOTICE")
                tools.now += timedelta(minutes=retry_delay)
                self.assertEqual(handle(case, tools, "")["state"], "HUMAN_REVIEW")
                self.assertEqual(handle(case, tools, "")["state"], "HUMAN_REVIEW")
                self.assertEqual(sum(c["tool"] == "support.notify" for c in tools.calls), attempts)
                self.assertEqual(sum(c["tool"] == "support.handoff" for c in tools.calls), 1)
                self.assertEqual((len(tools.bookings), len(tools.notices)), (1, 0))
                self.assertIsNone(case.resolved_at)

    def test_repeat_miss_or_opt_out(self):
        for text in ("I've now had two no-shows for my return pickup.", "This is the second no-show.",
                     "The driver missed both collections.", "Both pickup attempts failed.",
                     "The courier missed my pickup and I don't want another driver.",
                     "I don’t need another courier.", "No more pickups please.", "Please don't send anyone else."):
            with self.subTest(text=text):
                row = run_case("P101", text=text)
                self.assertEqual((row["state"], row["bookings_created"]), ("HUMAN_REVIEW", 0))
        message = "The courier missed my pickup. I don't want to miss another pickup."
        self.assertEqual(run_case("P101", text=message)["state"], "OFFERED")

    def test_cancel_pending(self):
        for incident in ("P132", "P108"):
            with self.subTest(incident=incident):
                tools = MockServices()
                case = Case(incident)
                handle(case, tools, tools.cases[incident]["sample"])
                handle(case, tools, "", selected_slot="A")
                self.assertEqual(handle(case, tools, "I don't want another driver.")["state"], "HUMAN_REVIEW")
                self.assertEqual(handle(case, tools, "")["state"], "HUMAN_REVIEW")
                self.assertEqual((len(tools.bookings), len(tools.notices)), (1, 0))

    def test_changed_instructions(self):
        messages = (
            "Actually, Wednesday doesn't work. Can we do Thursday instead?",
            "I want to cancel.",
            "Sorry, do you mean this Thursday or next Thursday?",
            "OK, thanks, but I won't be home on Wednesday.",
        )
        for case_id in ("P132", "P108"):
            for message in messages:
                with self.subTest(case_id=case_id, message=message):
                    tools = MockServices()
                    case = Case(case_id)
                    handle(case, tools, tools.cases[case_id]["sample"], message_id="first")
                    handle(case, tools, "", selected_slot="A")
                    result = handle(case, tools, message, message_id="change")
                    self.assertEqual(result["state"], "HUMAN_REVIEW")
                    self.assertEqual(tools.queue[case_id]["owner"], "Support Operations")
                    self.assertTrue(any(message in line for line in tools.queue[case_id]["evidence"]))
                    self.assertTrue(any("BK-" + case_id in line for line in tools.queue[case_id]["evidence"]))
                    handle(case, tools, message, message_id="change")
                    handle(case, tools, "")
                    self.assertEqual((len(tools.bookings), len(tools.notices)), (1, 0))
                    self.assertEqual(sum(call["tool"] == "carrier.book_once" for call in tools.calls), 1)
                    self.assertEqual(sum(call["tool"] == "support.handoff" for call in tools.calls), 1)
                    self.assertIsNone(case.resolved_at)

    def test_conflicting_buttons(self):
        for second, final in (("A", "RESOLVED"), ("B", "HUMAN_REVIEW")):
            with self.subTest(second=second):
                tools = MockServices()
                case = Case("P132")
                handle(case, tools, self.message)
                handle(case, tools, "", selected_slot="A")
                self.assertEqual(handle(case, tools, "", selected_slot=second)["state"], final)
                self.assertEqual(len(tools.bookings), 1)
                self.assertEqual(len(tools.notices), int(second == "A"))

    def test_pending_acknowledgement(self):
        for case_id in ("P132", "P108"):
            for text, event_id in (("Got it.", "reply"), ("Okay!", "reply"), (self.message, "first")):
                with self.subTest(case_id=case_id, text=text):
                    tools = MockServices()
                    case = Case(case_id)
                    handle(case, tools, self.message, message_id="first")
                    handle(case, tools, "", selected_slot="A")
                    self.assertEqual(handle(case, tools, text, message_id=event_id)["state"], "RESOLVED")
                    self.assertEqual((len(tools.bookings), len(tools.notices)), (1, 1))
                    self.assertFalse(tools.queue)

    def test_conflicting_visit(self):
        messages = (
            "That's twice now. The courier didn't turn up today either. I'm furious.",
            "That’s twice now. The courier didn’t turn up today either. I’m furious.",
            "This is the second time the driver did not arrive.",
            "The courier called and said he is still on his way to collect my return today.",
            "The driver just texted that she’s on her way to my house.",
        )
        for message in messages:
            with self.subTest(message=message):
                tools = MockServices()
                case = Case("P101")
                self.assertEqual(handle(case, tools, message)["state"], "HUMAN_REVIEW")
                task = tools.queue["P101"]
                self.assertEqual(task["owner"], "Support Operations")
                self.assertTrue(any(message in line for line in task["evidence"]))
                self.assertTrue(any("recorded missed attempts: 1" in line for line in task["evidence"]))
                handle(case, tools, "", selected_slot="A")
                self.assertFalse(tools.bookings)
                self.assertFalse(tools.notices)
        self.assertEqual(run_case("P102", text="Is the courier still coming?")["state"], "WAITING_CARRIER")

    def test_human_request(self):
        for message in ("Can I speak to a human about this failed pickup?",
                        "Please connect me to support.", "I'd like to talk to a real person."):
            with self.subTest(message=message):
                tools = MockServices()
                case = Case("P101")
                handle(case, tools, self.message)
                self.assertEqual(handle(case, tools, message, selected_slot="A")["state"], "HUMAN_REVIEW")
                self.assertEqual(tools.queue["P101"]["owner"], "Support Operations")
                self.assertFalse(tools.bookings)
                self.assertFalse(tools.notices)

    def test_clarification_expires(self):
        case = Case("P101")
        self.assertEqual(handle(case, self.tools, "Hi, can someone help?", message_id="initial")["state"],
                         "NEEDS_CLARIFICATION")
        self.tools.now += timedelta(hours=47, minutes=59)
        self.assertEqual(handle(case, self.tools, "Hi, can someone help?", message_id="initial")["state"],
                         "NEEDS_CLARIFICATION")
        self.tools.now += timedelta(minutes=1)
        self.assertEqual(handle(case, self.tools, "")["state"], "HUMAN_REVIEW")
        self.tools.now += timedelta(days=3)
        handle(case, self.tools, "")
        self.assertEqual(sum(c["tool"] == "support.handoff" for c in self.tools.calls), 1)
        self.assertFalse(self.tools.bookings)
        self.assertIsNone(case.resolved_at)

    def test_clarification_answer(self):
        case = Case("P101")
        handle(case, self.tools, "Can you help?")
        self.tools.now += timedelta(hours=2)
        self.assertEqual(handle(case, self.tools, self.message)["state"], "OFFERED")
        self.assertFalse(self.tools.queue)

    def test_original_window(self):
        reply = run_case("P112", scripted=True)["turns"][0]["message"]
        self.assertIn("Wed 25 Nov at 16:00", reply)
        self.assertNotIn("still open", reply)
        self.assertIn("can't confirm", reply)
        waiting = run_case("P102", scripted=True)["turns"][0]["message"]
        self.assertIn("window has ended", waiting)
        self.assertIn("can't confirm a later visit", waiting)
        self.assertIn("19:00", waiting)

    def test_first_miss_required(self):
        for after_offer in (False, True):
            for missing_count in (True, False):
                with self.subTest(after_offer=after_offer, missing_count=missing_count):
                    tools = MockServices()
                    case = Case("P101")
                    if after_offer:
                        handle(case, tools, self.message)
                    if missing_count:
                        del tools.cases["P101"]["misses"]
                    else:
                        tools.cases["P101"]["misses"] = 0
                    result = handle(case, tools, self.message, selected_slot="A" if after_offer else None)
                    self.assertEqual(result["state"], "HUMAN_REVIEW")
                    self.assertFalse(tools.bookings)
                    self.assertFalse(case.offered)

    def test_visit_timestamps(self):
        text = "I was out and missed the courier for my return pickup. Can I book another pickup?"
        for attempted_at in (None, "2026-11-24T16:10:00+01:00"):
            with self.subTest(attempted_at=attempted_at):
                tools = MockServices()
                tools.cases["P103"]["attempted_at"] = attempted_at
                result = handle(Case("P103"), tools, text)
                self.assertEqual(result["state"], "HUMAN_REVIEW")
                self.assertNotIn("differ", result["message"])
                evidence = "\n".join(tools.queue["P103"]["evidence"])
                self.assertIn(f"shopper message received at {tools.now.isoformat()}", evidence)
                self.assertIn(f"carrier lookup at {tools.now.isoformat()}", evidence)
                self.assertIn(f"attempted visit at {attempted_at}" if attempted_at else "was not provided", evidence)

    def test_inquiry_deadline(self):
        case = Case("P102")
        handle(case, self.tools, self.tools.cases["P102"]["sample"])
        first_inquiry = self.tools.inquiries["P102"]
        self.tools.now += timedelta(minutes=15)
        self.assertEqual(handle(case, self.tools, "Thanks!")["state"], "WAITING_CARRIER")
        self.assertEqual(self.tools.inquiries["P102"], first_inquiry)
        self.tools.now += timedelta(minutes=15)
        self.assertEqual(handle(case, self.tools, "")["state"], "HUMAN_REVIEW")

    def test_address_validation(self):
        case = Case("P106")
        handle(case, self.tools, self.tools.cases["P106"]["sample"])
        self.assertEqual(handle(case, self.tools, "I've updated my address.")["state"], "NEED_ADDRESS")
        del self.tools.cases["P106"]["missing_field"]
        self.assertEqual(handle(case, self.tools, "")["state"], "OFFERED")
        self.assertFalse(self.tools.bookings)

    def test_thanks_keeps_the_original_email_open(self):
        self.open()
        offer_number = self.case.offer_number
        self.tools.now += timedelta(hours=4)
        self.assertEqual(handle(self.case, self.tools, "Thanks!")["state"], "OFFERED")
        self.assertEqual(self.case.offer_number, offer_number)
        self.tools.now += timedelta(hours=8)
        self.assertEqual(handle(self.case, self.tools, "")["state"], "OFFERED")
        self.assertFalse(self.tools.bookings)

    def test_pending_booking_acknowledgement(self):
        for case_id in ("P132", "P108"):
            with self.subTest(case_id=case_id):
                tools = MockServices()
                case = Case(case_id)
                handle(case, tools, tools.cases[case_id]["sample"])
                handle(case, tools, "", selected_slot="A")
                self.assertEqual(handle(case, tools, "Thanks!")["state"], "RESOLVED")
                self.assertEqual(len(tools.bookings), 1)
                self.assertEqual(len(tools.notices), 1)

    def test_invalid_confirmation(self):
        for change in ({"slot": "B"}, {"start": "2026-11-26T14:00:00+01:00"},
                       {"reference": "BK-other"}, {"reference": "  "}, None, "unreadable"):
            with self.subTest(change=change):
                tools = MockServices()
                case = Case("P108")
                handle(case, tools, tools.cases[case.case_id]["sample"])
                handle(case, tools, "", selected_slot="A")
                if isinstance(change, dict):
                    tools.bookings[case.case_id].update(change)
                else:
                    tools.bookings[case.case_id] = change
                self.assertEqual(handle(case, tools, "")["state"], "HUMAN_REVIEW")
                self.assertFalse(tools.notices)

    def test_carrier_silence_bounded_one_inquiry(self):
        case = Case("P102")
        self.assertEqual(handle(case, self.tools, self.tools.cases["P102"]["sample"])["state"], "WAITING_CARRIER")
        self.tools.now += timedelta(minutes=29)
        self.assertEqual(handle(case, self.tools, "")["state"], "WAITING_CARRIER")
        self.tools.now += timedelta(minutes=1)
        self.assertEqual(handle(case, self.tools, "")["state"], "HUMAN_REVIEW")
        self.assertEqual(sum(c["tool"] == "carrier.ask_for_update" for c in self.tools.calls), 1)
        self.assertEqual(self.tools.queue["P102"]["owner"], "Support Operations")
        self.assertNotEqual(self.tools.queue["P102"]["next_step"], self.tools.queue["P102"]["reason"])
        self.assertIn("update the shopper", self.tools.queue["P102"]["next_step"])
        self.assertIn("still haven't heard back", self.tools.inquiry_updates["Q-P102"])
        handle(case, self.tools, "")
        self.assertEqual(sum(c["tool"] == "support.send_inquiry_update" for c in self.tools.calls), 1)

    def test_new_carrier_evidence_replaces_wait(self):
        case = Case("P102")
        handle(case, self.tools, self.tools.cases["P102"]["sample"])
        self.tools.cases["P102"].update(status="missed", misses=1)
        self.assertEqual(handle(case, self.tools, "")["state"], "OFFERED")
        self.assertIn("Which time works", self.tools.inquiry_updates["Q-P102"])

    def test_silent_shopper(self):
        result = run_case("P101", advance_minutes=48 * 60)
        self.assertEqual(result["state"], "AWAITING_REPLY")
        self.assertFalse(result["autonomous_under_24h"])
        self.assertEqual(result["bookings_created"], 0)

    def test_financial_handoff(self):
        for case_id in ("P105", "P113"):
            row = run_case(case_id, scripted=True)
            self.assertEqual(row["owner"], "Merchant Operations")
            self.assertEqual(row["bookings_created"], 0)
            self.assertTrue(any(e.startswith("carrier lookup at ") for e in row["turns"][0]["evidence"]))

    def test_fee_questions(self):
        for text in ("Who pays for another collection?", "How much does a replacement pickup cost?",
                     "Is there a fee for another pickup?", "Will you charge me for the pickup?",
                     "Will another collection be free?"):
            with self.subTest(text=text):
                row = run_case("P101", text=text)
                self.assertEqual((row["state"], row["owner"]), ("HUMAN_REVIEW", "Merchant Operations"))
                self.assertEqual(row["bookings_created"], 0)
        for text in ("The courier never took the box.", "My parcel was not collected."):
            self.assertEqual(run_case("P101", text=text)["state"], "OFFERED")
        self.assertNotEqual(read_intent("Who is in charge of the pickup?"), "money")
        self.assertEqual(read_intent("I don't think my parcel was collected."), "unknown")

    def test_non_financial_status_gates(self):
        for case_id in ("P103", "P104", "P109", "P110"):
            with self.subTest(case_id=case_id):
                row = run_case(case_id, scripted=True)
                self.assertEqual(row["state"], "HUMAN_REVIEW")
                self.assertEqual(row["owner"], "Support Operations")
                self.assertEqual(row["bookings_created"], 0)
                self.assertFalse(row["autonomous_under_24h"])

    def test_repeat_failure_owner(self):
        row = run_case("P101", text="This is the second time nobody has shown up.")
        self.assertEqual(row["state"], "HUMAN_REVIEW")
        self.assertIn("reported multiple", row["next_step"])

    def test_verified_address(self):
        case = Case("P106")
        result = handle(case, self.tools, self.tools.cases["P106"]["sample"])
        self.assertEqual(result["state"], "NEED_ADDRESS")
        self.assertFalse(self.tools.bookings)
        handle(case, self.tools, "")
        self.assertEqual(len(self.tools.address_alerts), 1)
        del self.tools.cases["P106"]["missing_field"]
        self.assertEqual(handle(case, self.tools, "")["state"], "OFFERED")

    def test_original_window_monitor(self):
        self.assertEqual(run_case("P111", scripted=True)["state"], "NEED_ADDRESS")
        self.assertEqual(run_case("P112", scripted=True)["turns"][0]["state"], "WINDOW_OPEN")
        self.assertEqual(run_case("P112", scripted=True)["bookings_created"], 0)

    def test_bound_return_id(self):
        row = run_case("P101", text="My courier missed pickup P105.", slot="A")
        calls = [call for turn in row["turns"] for call in turn["tool_calls"]]
        self.assertTrue(all(c["case"] == "P101" for c in calls))

    def test_unrecognised_text_must_clarify(self):
        row = run_case("P101", text="?? xyz")
        self.assertEqual(row["state"], "NEEDS_CLARIFICATION")
        self.assertFalse(row["turns"][0]["tool_calls"])

    def test_escalation_is_sticky_on_replay(self):
        case = Case("P104")
        handle(case, self.tools, self.message)
        self.assertEqual(handle(case, self.tools, "", selected_slot="A")["state"], "HUMAN_REVIEW")
        self.assertEqual(len(self.tools.queue), 1)
        self.assertFalse(self.tools.bookings)

    def test_report_serializable_and_kpis(self):
        data = json.loads(json.dumps(report()))
        self.assertEqual(len(data["cases"]), len(self.tools.cases))
        for row in data["cases"]:
            self.assertEqual(row["autonomous_under_24h"], row["state"] == "RESOLVED")
            if row["state"] == "RESOLVED":
                self.assertEqual(row["bookings_created"], 1)
                self.assertEqual(row["confirmation_notices_delivered"], 1)


class IntentTests(unittest.TestCase):
    def test_simple_unseen_wording(self):
        self.assertEqual(read_intent("Nobody showed up to collect my return parcel"), "pickup")
        self.assertEqual(read_intent("Can I get compensated for the time I lost?"), "money")
        self.assertNotEqual(read_intent("exchange the shoes"), "pickup")

    def test_model_output(self):
        for answer, expected in [('{"intent":"pickup"}', "pickup"), ('{"intent":"approve_refund"}', "unknown"),
                                 ('broken', "unknown"), ('{"intent":[]}', "unknown")]:
            self.assertEqual(ollama_intent("The courier never came", "test", lambda _: answer), expected)
        def down(payload):
            raise TimeoutError()
        self.assertEqual(ollama_intent("I waited all afternoon", "test", down), "unknown")
        self.assertEqual(ollama_intent("I want compensation", "test", down), "money")


if __name__ == "__main__":
    unittest.main()

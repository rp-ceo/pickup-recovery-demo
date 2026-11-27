"""Replay mixed pickup incidents on one mock clock at 6 and 12 new cases per minute."""
from collections import Counter
from copy import deepcopy
from datetime import timedelta
from heapq import heappop, heappush
from itertools import count
import unittest

from carrier import MockServices
from pickup import Case, handle


INCIDENTS = {
    "P118": [(0, "carrier"), (1, "carrier"), (4, "choose"), (5, "choose")],
    "P107": [(0, "report"), (4, "choose"), (5, "reconcile"), (6, "reconcile")],
    "P119": [(0, "report"), (35, "collected"), (36, "collected")],
    "P102": [(0, "report"), (10, "missed"), (12, "choose")],
    "P113": [(0, "report"), (2, "choose")],
    "P117": [(0, "report"), (1, "wrong_address"), (2, "choose")],
}


class PilotVolumeTests(unittest.TestCase):
    def test_mixed_arrivals(self):
        for copies_per_minute in (1, 2):
            with self.subTest(arrivals_per_minute=len(INCIDENTS) * copies_per_minute):
                self.check_burst(copies_per_minute)

    def check_burst(self, copies_per_minute):
        tools = MockServices()
        start = tools.now
        cases = {}
        events = []
        sequence = count()
        by_kind = {kind: set() for kind in INCIDENTS}
        dispatched = set()

        for minute in range(8):
            for copy_index in range(copies_per_minute):
                for kind, timeline in INCIDENTS.items():
                    key = f"{kind}-{minute}-{copy_index}"
                    cases[key] = Case(key)
                    by_kind[kind].add(key)
                    tools.cases[key] = deepcopy(tools.cases[kind])
                    for offset, action in timeline:
                        when = start + timedelta(minutes=minute + offset)
                        heappush(events, (when, next(sequence), key, action))

        while events:
            tools.now, _, key, action = heappop(events)
            case, record = cases[key], tools.cases[key]
            if action == "report":
                handle(case, tools, record["sample"], message_id="shopper-report")
                if case.state == "WAITING_CARRIER":
                    inquiry, _ = tools.inquiries[key]
                    due_at = tools.pending_inquiry_updates[inquiry]
                    heappush(events, (due_at, next(sequence), key, "callback"))
            elif action == "choose":
                handle(case, tools, "", selected_slot="A", offer_number=1)
            elif action == "wrong_address":
                handle(case, tools, "Wait, that address isn’t mine.", message_id="address-change")
            elif action == "callback":
                inquiry, _ = tools.inquiries[key]
                if inquiry in tools.pending_inquiry_updates:
                    dispatched.add(key)
                    handle(case, tools, "")
            elif action == "reconcile":
                handle(case, tools, "")
            else:
                if action == "missed":
                    record.update(status="missed", misses=1)
                elif action == "collected":
                    record.update(status="collected")
                else:
                    self.assertEqual(action, "carrier")
                handle(case, tools, "", carrier_event=True)

        booked = by_kind["P118"] | by_kind["P107"] | by_kind["P102"]
        human = by_kind["P119"] | by_kind["P113"] | by_kind["P117"] | by_kind["P107"]
        confirmed = booked - by_kind["P107"]
        self.assertEqual(set(tools.bookings), booked)
        self.assertEqual(set(tools.notices), {tools.bookings[k]["reference"] for k in confirmed})
        self.assertEqual(set(tools.queue), human)
        self.assertTrue(all(cases[k].state == "RESOLVED" for k in confirmed))
        self.assertTrue(all(cases[k].state == "HUMAN_REVIEW" for k in human))
        for key in by_kind["P113"]:
            self.assertEqual(tools.queue[key]["owner"], "Merchant Operations")
        for key in by_kind["P117"] | by_kind["P119"]:
            self.assertEqual(tools.queue[key]["owner"], "Support Operations")
        for key in by_kind["P119"]:
            self.assertEqual(tools.queue[key]["latest_carrier_record"]["status"], "collected")

        def calls(name):
            return Counter(call["case"] for call in tools.calls if call["tool"] == name)

        self.assertEqual(calls("carrier.book_once"), Counter(booked))
        self.assertEqual(calls("support.notify"), Counter(confirmed))
        self.assertEqual(calls("support.send_pickup_options"), Counter(by_kind["P118"]))
        for key in confirmed:
            reference = tools.bookings[key]["reference"]
            self.assertEqual(reference, f"BK-{key}")
            self.assertEqual(tools.notices[reference], f"NOTICE-{reference}")

        inquiries = by_kind["P102"] | by_kind["P119"]
        self.assertEqual(dispatched, by_kind["P119"])
        self.assertEqual(calls("carrier.ask_for_update"), Counter(inquiries))
        self.assertEqual(calls("support.send_inquiry_update"), Counter(inquiries))
        self.assertEqual(Counter(r["case_id"] for r in tools.callback_receipts), Counter(inquiries))
        self.assertFalse(tools.pending_inquiry_updates)
        for receipt in tools.callback_receipts:
            self.assertEqual(receipt["inquiry"], tools.inquiries[receipt["case_id"]][0])
            self.assertFalse(receipt["overdue"])
            self.assertEqual(receipt["minutes_late"], 0)

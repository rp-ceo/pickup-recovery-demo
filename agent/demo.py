"""Run a pickup case or export the tool trace for all fictional cases."""
import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timedelta

from carrier import MockServices, TimeZoneConfigurationError
from choices import discussing_offered_time, is_acknowledgement
from email_reply import current_reply
from intent import read_intent
from pickup import Case, WAIT, handle
from readiness import SCENARIOS, example


NEXT = {
    "OPEN": ("Pickup agent", "Inspect the ticket and carrier record."),
    "OFFERED": ("Shopper", "Choose an available slot."),
    "NEEDS_SLOT_CHOICE": ("Shopper", "Reply with a current option or choose it in the portal."),
    "SLOT_CHANGED": ("Shopper", "Choose a time from the new offer."),
    "AWAITING_REPLY": ("Shopper", "Reply or open the link to request current pickup windows."),
    "NEED_ADDRESS": ("Shopper", "Correct the carrier-flagged detail in the return portal."),
    "NEEDS_CLARIFICATION": ("Shopper", "Clarify the request. Support follows up after 48 hours."),
    "WINDOW_OPEN": ("Pickup agent", "Check for a carrier update when the recorded window ends."),
    "WAITING_CARRIER": ("Pickup agent", "Recheck the carrier record and update the shopper by the inquiry deadline."),
    "BOOKING_UNCERTAIN": ("Pickup agent", "Check the original attempt with the pilot carrier's lookup."),
    "CONFIRMED_AWAITING_NOTICE": ("Pickup agent", "Retry before the cutoff. Escalate if delivery fails."),
    "RESOLVED": ("Pickup monitoring", "Monitor the physical collection separately."),
}


def run_case(case_id, text=None, slot=None, advance_minutes=0, *, scripted=False, classify=read_intent,
             reply=None, after_booking=None, late_timer=False, reply_after_hours=0):
    tools = MockServices()
    record = tools.cases[case_id]
    case = Case(case_id)
    turns = []

    def step(event_source, event, text="", choice=None, offer_number=None):
        before = len(tools.calls)
        reply_text = current_reply(text, case.last_reply)
        help_contact = (event_source == "shopper_message" and bool(reply_text)
                        and not is_acknowledgement(case, reply_text)
                        and not (case.offered and discussing_offered_time(case, reply_text, None)))
        result = handle(case, tools, text, selected_slot=choice, offer_number=offer_number,
                        carrier_event=event_source == "carrier_event",
                        message_id=str(len(turns) + 1) if text else None, classify=classify)
        if case.state == "HUMAN_REVIEW":
            task = tools.queue[case_id]
            owner, next_step = task["owner"], task["next_step"]
        else:
            owner, next_step = NEXT[case.state]
        if case.state == "RESOLVED" and case.collection_scan_observed_at:
            owner = "Pickup monitoring"
            next_step = "Collection scan received. Keep the carrier evidence with the return."
        turns.append({"at": tools.now.isoformat(), "event_source": event_source, "event": event, **result,
                      "collection_scan_observed_at": (case.collection_scan_observed_at.isoformat()
                                                      if case.collection_scan_observed_at else None),
                      "shopper_help_contact": bool(help_contact), "owner": owner,
                      "next_step": next_step, "tool_calls": tools.calls[before:]})

    def advance(minutes, simulate_delay=False):
        """Run scheduled checks due before the clock reaches the next event."""
        target = tools.now + timedelta(minutes=minutes)
        dispatched = False
        if case.state == "WINDOW_OPEN" and not simulate_delay:
            window_end = tools.local_time(datetime.fromisoformat(record["window_end"]))
            if tools.now < window_end <= target:
                tools.now = window_end
                step("timer", "Original pickup window ended")
                dispatched = True
        if case.state == "WAITING_CARRIER" and not simulate_delay:
            _, started = tools.inquiries[case_id]
            due = started + WAIT
            if tools.now <= due <= target:
                tools.now = due
                step("timer", "Promised carrier update is due")
                dispatched = True
        tools.now = target
        return dispatched

    first = record["sample"] if text is None else text
    if text is None and "initial_event" in record:
        step("carrier_event", record["initial_event"])
    else:
        step("shopper_message", first, first)

    if scripted:
        for entry in record.get("replay", []):
            dispatched = advance(entry["after_minutes"], entry.get("simulate_delay", False))
            if "select" in entry:
                choice = entry["select"]
                offer = entry["offer"]
                step("shopper_selection", f"Shopper selects slot {choice} from offer {offer}",
                     choice=choice, offer_number=offer)
            elif "message" in entry:
                step("shopper_message", entry["message"], entry["message"])
            elif "carrier_event" in entry:
                for field in ("status", "missing_field", "slots", "collected_at"):
                    if field in entry:
                        record[field] = entry[field]
                step("carrier_event", entry["carrier_event"])
            elif entry.get("timer") and not dispatched:
                step("timer", "Simulated follow-up timer")
    else:
        original_offer = case.offer_number
        if reply_after_hours:
            advance(reply_after_hours * 60)
        if reply is not None:
            step("shopper_message", reply, reply)
        if slot is not None:
            if not original_offer and case.state != "HUMAN_REVIEW":
                raise ValueError("No slot has been offered. No booking attempted.")
            event = "Shopper selects slot " + slot
            if case.state == "HUMAN_REVIEW":
                event = "Shopper tries slot " + slot + " after handoff"
            step("shopper_selection", event, choice=slot, offer_number=original_offer)
        if after_booking is not None:
            step("shopper_message", after_booking, after_booking)
        if advance_minutes and not advance(advance_minutes, late_timer):
            step("timer", "Simulated follow-up timer")
    last = turns[-1]
    elapsed = ((case.resolved_at - case.opened_at).total_seconds() / 60
               if case.resolved_at is not None else None)
    contacts = sum(turn["shopper_help_contact"] for turn in turns)
    return {"id": case_id, "label": record["label"], "group": record["group"], "turns": turns, "state": last["state"],
            "owner": last["owner"], "next_step": last["next_step"],
            "origin": case.origin, "carrier_callback_receipts": tools.callback_receipts,
            "shopper_help_contacts": contacts, "repeat_shopper_help_contacts": max(0, contacts - 1),
            "pickup_offers_delivered": sum(receipt is not None for receipt in tools.offer_receipts.values()),
            "first_confirmed_miss_at": (case.first_confirmed_miss_at.isoformat()
                                        if case.first_confirmed_miss_at else None),
            "collection_scan_observed_at": (case.collection_scan_observed_at.isoformat()
                                            if case.collection_scan_observed_at else None),
            "collected_at": case.collected_at.isoformat() if case.collected_at else None,
            "simulation_minutes_to_resolution": elapsed,
            "autonomous_under_24h": last["state"] == "RESOLVED" and elapsed is not None and elapsed < 1440,
            "bookings_created": len(tools.bookings), "confirmation_notices_delivered": len(tools.notices)}


def report():
    initial = MockServices()
    description = "Scripted examples with fictional carrier records, simulated delivery and an offline classifier."
    return {"mode": description,
            "timezone": initial.slot_timezone.key,
            "as_of": initial.now.isoformat(),
            "readiness": {name: example(name) for name in SCENARIOS},
            "cases": [run_case(case_id, scripted=True) for case_id in initial.cases]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", nargs="?", default="P101", choices=list(MockServices().cases))
    parser.add_argument("--message", help="A custom pickup message from the shopper on this return")
    parser.add_argument("--reply", help="Send a second shopper message before clicking the original offer")
    parser.add_argument("--reply-after", type=int, default=0, metavar="HOURS",
                        help="Hours to wait before the shopper replies or uses the original link")
    parser.add_argument("--after-booking", help="Send a follow-up after the shopper's choice")
    parser.add_argument("--late-timer", action="store_true",
                        help="Delay a due callback until the simulated clock stops")
    parser.add_argument("--choose", metavar="SLOT", help="Simulate the shopper explicitly selecting an offered slot")
    parser.add_argument("--advance", type=int, default=0, metavar="MINUTES", help="Simulate a follow-up timer")
    parser.add_argument("--ollama-model", help="Use an already installed local model for message interpretation")
    parser.add_argument("--report", action="store_true", help="Offline-only JSON traces for all mock cases")
    parser.add_argument("--readiness", choices=SCENARIOS, help="Run a fictional first-visit check")
    parser.add_argument("--json", action="store_true", help="Machine-readable output for one mock case")
    args = parser.parse_args()
    if args.readiness:
        print(json.dumps(example(args.readiness), ensure_ascii=False, indent=2))
        return
    if args.advance < 0:
        parser.error("Advance must be positive or zero.")
    if args.reply_after < 0 or (args.reply_after and args.reply is None and args.choose is None):
        parser.error("--reply-after needs a reply or selection and a non-negative number of hours.")
    if args.late_timer and not args.advance:
        parser.error("--late-timer needs a positive --advance value.")
    if args.report:
        if args.ollama_model:
            parser.error("The reproducible report uses the offline classifier. Select a single case for the local LLM.")
        print(json.dumps(report(), ensure_ascii=False, indent=2))
        return
    classify = read_intent
    mode = "offline rules and example matching"
    model_calls = Counter()
    if args.ollama_model:
        from local_model import classify_reply
        mode = "rules with Ollama fallback: " + args.ollama_model

        def classify(text):
            return classify_reply(text, args.ollama_model, outcomes=model_calls)
    if args.after_booking is not None and args.choose is None and args.reply is None:
        parser.error("--after-booking needs a --choose or --reply step first.")
    custom = args.message is not None or args.reply is not None or args.choose is not None or args.advance != 0
    try:
        result = run_case(args.case, args.message, args.choose, args.advance, scripted=not custom, classify=classify,
                          reply=args.reply, after_booking=args.after_booking, late_timer=args.late_timer,
                          reply_after_hours=args.reply_after)
    except ValueError as error:
        parser.error(str(error))
    if args.ollama_model:
        result["model_calls"] = dict(model_calls)
    if args.json:
        print(json.dumps({"mode": mode, **result}, ensure_ascii=False, indent=2))
        return
    print(f"Mock case {result['id']} · {result['label']} · {mode}")
    if args.ollama_model:
        counts = ", ".join(f"{status}: {count}" for status, count in model_calls.items())
        print("Model calls: " + (counts or "0"))
    for turn in result["turns"]:
        print(f"\n{turn['at']} | {turn['event']}")
        for call in turn["tool_calls"]:
            print(f"  {call['tool']} -> {call['result']}")
        print(f"{turn['state']}: {turn['message']}")
    print(f"\nOwner: {result['owner']}. Next: {result['next_step']}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        main()
    except TimeZoneConfigurationError as error:
        raise SystemExit(str(error)) from None

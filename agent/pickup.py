"""Decision policy for one mock pickup incident; separate from free-text extraction."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from carrier import IncompleteCarrierRecord, LostAcknowledgement
from choices import Reply, asks_booking_details, can_read_booking, change_after_booking, is_acknowledgement
from choices import read_choice, requested_day
from email_reply import current_reply
from intent import PICKUP_PRICING, booking_concern, explicit_intent, read_intent
from messages import SPANISH, answer_offer, checking_carrier, confirmed, language_help, offer_message
from messages import reply_language, shopper_message, simple_foreign_reply
from states import State


WAIT = timedelta(minutes=30)
SHOPPER_WAIT = timedelta(hours=48)
NOTICE_WAIT = timedelta(minutes=30)
PENDING_CONFIRMATION = {State.BOOKING_UNCERTAIN, State.CONFIRMED_AWAITING_NOTICE}
ACTIVE_OFFER = {State.OFFERED, State.SLOT_CHANGED, State.NEEDS_SLOT_CHOICE}


@dataclass
class Case:
    case_id: str
    state: State = State.OPEN
    language: str = "en"
    offered: dict = field(default_factory=dict)
    offered_starts: dict = field(default_factory=dict)
    offered_ends: dict = field(default_factory=dict)
    offer_order: tuple = ()
    offer_number: int = 0
    accepted_slot: str = None
    accepted_window: str = None
    accepted_start: str = None
    accepted_end: str = None
    carrier_observation: dict = None
    support_reviewing_visit: bool = False
    booking_reference: str = None
    processed_messages: set = field(default_factory=set)
    evidence: list = field(default_factory=list)
    waiting_since: datetime = None
    opened_at: datetime = None
    resolved_at: datetime = None
    first_confirmed_miss_at: datetime = None
    collection_scan_observed_at: datetime = None
    collected_at: datetime = None
    first_notice_failure_at: datetime = None
    last_reply: str = ""
    origin: str = None

    def note(self, fact):
        if fact not in self.evidence:
            self.evidence.append(fact)

    def email_expired(self, now):
        return (self.waiting_since is not None
                and now.astimezone(timezone.utc) - self.waiting_since.astimezone(timezone.utc) >= SHOPPER_WAIT)

    def reply(self, state, message):
        if state not in ACTIVE_OFFER:
            self.offered.clear()
            self.offered_starts.clear()
            self.offered_ends.clear()
        self.state = state
        self.last_reply = message
        return {"state": state, "message": message, "evidence": list(self.evidence)}


def handoff(case, tools, reason, next_step, owner="Support Operations", **details):
    tools.handoff(case.case_id, owner, reason, next_step, case.evidence)
    return case.reply(State.HUMAN_REVIEW, shopper_message(case, reason, **details))


def matches_choice(case, booking):
    return (booking and case.accepted_slot and booking.get("slot") == case.accepted_slot
            and booking.get("window") == case.accepted_window and booking.get("start") == case.accepted_start
            and case.accepted_end and booking.get("end") == case.accepted_end
            and isinstance(booking.get("reference"), str) and booking["reference"].strip()
            and (case.booking_reference is None or booking["reference"] == case.booking_reference))


def finish(case, tools, booking):
    if not matches_choice(case, booking):
        case.resolved_at = None
        return handoff(case, tools, "Unverified booking",
                       "Reconcile the booking reference and the shopper's accepted window before "
                       "confirming.")
    case.booking_reference = booking["reference"]
    case.note(f"carrier booking {booking['reference']}: {booking['window']}")
    notice = tools.notices.get(booking["reference"])
    if not notice:
        latest = tools.lookup(case.case_id)
        case.carrier_observation = observed_visit(case, latest, tools.now)
        if latest.get("missing_field"):
            case.note("carrier address validation flagged: " + latest["missing_field"])
            return handoff(case, tools, "Address flagged",
                           "Verify the address and the existing booking with the carrier before "
                           "confirming the pickup.")
        if latest["status"] not in {"scheduled", "missed"} or (latest.get("misses") or 0) > 1:
            case.note(f"carrier record before first confirmation: {latest['status']}; "
                      f"missed attempts={latest.get('misses')}")
            return handoff(case, tools, "Visit status changed",
                           "Reconcile the current visit status and the existing booking before updating "
                           "the shopper.")
        if tools.now >= datetime.fromisoformat(case.accepted_start):
            return handoff(case, tools, "Window already started",
                           "Check the booking and collection with the carrier, then contact the shopper "
                           "before arranging another visit.")
        deadline = case.first_notice_failure_at + NOTICE_WAIT if case.first_notice_failure_at else None
        if deadline is None or tools.now < deadline:
            notice = tools.notify_once(case.case_id, booking)
        if not notice:
            if case.first_notice_failure_at is not None:
                return handoff(case, tools, "Confirmation undelivered",
                               "Contact the shopper through another channel and verify the existing "
                               "booking before scheduling anything else.")
            case.first_notice_failure_at = tools.now
            case.note(f"customer notification failed at {tools.now.isoformat()} for booking {booking['reference']}")
            return case.reply(State.CONFIRMED_AWAITING_NOTICE, shopper_message(case, "Notice pending"))
    case.note("customer notification receipt " + notice)
    case.resolved_at = tools.notice_delivered_at[booking["reference"]]
    return case.reply(State.RESOLVED, confirmed(case, booking))


def waiting(case, tools):
    inquiry, started = tools.inquire(case.case_id, WAIT)
    cutoff = started + WAIT
    case.note(f"carrier inquiry {inquiry}, opened {started.isoformat()}")
    if tools.now >= cutoff:
        case.support_reviewing_visit = True
        return handoff(case, tools, "Carrier silent",
                       "Verify the attempt with the carrier and update the shopper.")
    return case.reply(State.WAITING_CARRIER, checking_carrier(case, inquiry, tools.local_time(cutoff)))


def present_windows(case, tools, *, refresh=False, choose_again=False, repeat_offer=False, complaint=None, choice=None):
    slots = tools.offer_slots(case.case_id)
    if not slots:
        return handoff(case, tools, "No available windows",
                       "Ask the carrier for alternative slots or collection methods and contact the "
                       "shopper.")
    starts = {slot: tools.slot_starts[slot] for slot in slots}
    ends = {slot: tools.slot_interval(slot)[1] for slot in slots}
    changed = refresh or (bool(case.offered) and
                          (slots != case.offered or starts != case.offered_starts or ends != case.offered_ends))
    if changed or not case.offered:
        remaining = {slot for slot, start in case.offered_starts.items() if tools.accepts_pickup(start)}
        only_elapsed = (remaining == slots.keys() and len(remaining) < len(case.offered)
                        and all(slots[slot] == case.offered[slot] and starts[slot] == case.offered_starts[slot]
                                and ends[slot] == case.offered_ends[slot] for slot in remaining))
        if not only_elapsed:
            case.offer_number += 1
            case.offer_order = tuple(slots)
            case.waiting_since = None
        case.offered = slots
        case.offered_starts = starts
        case.offered_ends = ends
    state = State.OFFERED
    if changed:
        state = State.SLOT_CHANGED
    elif choose_again:
        state = State.NEEDS_SLOT_CHOICE
    notice = offer_message(case, changed, repeat_offer or choose_again, complaint)
    if choice and not changed:
        notice = answer_offer(case, choice) + " " + notice
    return case.reply(state, notice)


def handle(case, tools, message, *, selected_slot=None, offer_number=None, message_id=None,
           classify=read_intent, carrier_event=False):
    """The inbox supplies message IDs. The slot button identifies the displayed offer."""
    if case.opened_at is None:
        case.opened_at = tools.now
    if case.origin is None:
        case.origin = "carrier" if carrier_event else ("shopper" if message else "timer")
    replay = message_id is not None and message_id in case.processed_messages
    if message and not replay:
        case.note(f"shopper message received at {tools.now.isoformat()}: {message}")
        if message_id is not None:
            case.processed_messages.add(message_id)
    if message:
        message = current_reply(message, case.last_reply)
        if not message:
            selected_slot = None
            if case.state == State.OPEN:
                case.waiting_since = tools.now
                return case.reply(State.NEEDS_CLARIFICATION, shopper_message(case, "Clarify pickup"))
        if SPANISH.search(message):
            case.language = "es"
    language = reply_language(message)
    previous_state = case.state
    was_waiting_for_carrier = previous_state == State.WAITING_CARRIER
    previous_offer = case.offer_number
    try:
        result = decide(case, tools, message, selected_slot, offer_number, replay, classify)
    except IncompleteCarrierRecord as error:
        case.resolved_at = None
        case.note(f"carrier lookup at {tools.now.isoformat()}: {error}")
        result = handoff(case, tools, "Incomplete carrier record",
                         "Check the incomplete or inconsistent carrier record before arranging a visit.")
    if language and (case.state in ACTIVE_OFFER or case.state in {State.HUMAN_REVIEW, State.NEEDS_CLARIFICATION}):
        result = case.reply(case.state, language_help(language, case.state == State.HUMAN_REVIEW, bool(case.offered)))
    if (previous_state == State.WINDOW_OPEN and case.state == State.WAITING_CARRIER
            and (carrier_event or not message) and selected_slot is None):
        receipt = tools.send_window_update(case.case_id, result["message"])
        if receipt:
            case.note(f"window-end update delivered: {receipt}")
            result["evidence"] = list(case.evidence)
        else:
            result = handoff(case, tools, "Pickup update undelivered",
                             "Check with the carrier and reach the shopper through another agreed "
                             "channel.")
    new_offer = bool(case.offered) and previous_offer != case.offer_number
    callback_due = was_waiting_for_carrier and case.state != State.WAITING_CARRIER
    if new_offer:
        if callback_due:
            receipt = tools.send_inquiry_update(case.case_id, result["message"], case.offer_number)
        elif carrier_event or (not message and selected_slot is None):
            receipt = tools.send_offer_once(case.case_id, case.offer_number, result["message"])
        else:
            case.waiting_since = tools.now
            return result
        if receipt:
            case.waiting_since = tools.now
            case.note(f"replacement options delivered to shopper: {receipt}")
            result["evidence"] = list(case.evidence)
        else:
            case.waiting_since = None
            result = handoff(case, tools, "Offer undelivered",
                             "Contact the shopper through the agreed channel before offering another "
                             "time.")
            if callback_due:
                tools.send_inquiry_update(case.case_id, result["message"])
    elif callback_due:
        tools.send_inquiry_update(case.case_id, result["message"])
    return result


def observed_visit(case, record, now):
    if record["status"] == "missed" and (record.get("misses") or 0) >= 1 and case.first_confirmed_miss_at is None:
        case.first_confirmed_miss_at = now
    if record["status"] == "collected":
        if case.collection_scan_observed_at is None:
            case.collection_scan_observed_at = now
            case.note(f"carrier collection scan first observed at {now.isoformat()}")
        if record.get("collected_at") and case.collected_at is None:
            case.collected_at = datetime.fromisoformat(record["collected_at"])
            case.note(f"carrier-reported collection time: {record['collected_at']}")
    fields = ("status", "misses", "attempted_at", "collected_at", "window_end", "missing_field")
    return {key: record[key] for key in fields if key in record}


def update_open_review(case, tools, message=""):
    task = tools.queue[case.case_id]
    reply = case.last_reply
    next_step = task["next_step"]
    try:
        observation = observed_visit(case, tools.lookup(case.case_id), tools.now)
    except IncompleteCarrierRecord as error:
        observation = {"unverified": str(error)}
    if observation != case.carrier_observation:
        previous = case.carrier_observation
        case.carrier_observation = observation
        detail = ", ".join(f"{key}={value}" for key, value in observation.items())
        case.note(f"carrier record read during human review at {tools.now.isoformat()}: {detail}")
        if observation.get("status") == "collected":
            reply = shopper_message(case, "Review collection")
            if case.support_reviewing_visit:
                next_step = ("Check the reported collection scan against the return and update the shopper. "
                             "Keep any new pickup on hold.")
        elif "unverified" in observation:
            reply = shopper_message(case, "Review status unavailable")
        elif previous is not None:
            reply = shopper_message(case, "Review updated")
            if case.support_reviewing_visit:
                next_step = "Review the updated carrier record with the shopper before arranging another visit."
    day = requested_day(message)
    if day and case.accepted_window and observation.get("status") in {"scheduled", "missed"}:
        next_step = (f"Check whether the earlier visit can be moved to {day}. "
                     "Confirm the change before closing this request.")
        reply = shopper_message(case, "Amendment under review", window=case.accepted_window, day=day)
    if task["evidence"] != case.evidence:
        tools.update_review(case.case_id, case.evidence, observation, next_step)
    return case.reply(State.HUMAN_REVIEW, reply)


def after_confirmation(case, tools, message, new_message, new_request, classify):
    after = tools.lookup(case.case_id)
    case.carrier_observation = observed_visit(case, after, tools.now)
    adverse = ((after.get("misses") or 0) >= 2 or after.get("missing_field")
               or after["status"] not in {"missed", "scheduled", "collected"})
    if adverse:
        case.note(f"carrier record read at {tools.now.isoformat()}: status={after['status']}; "
                  f"missed attempts={after.get('misses', 'unknown')}")
        case.resolved_at = None
        return handoff(case, tools, "New carrier evidence",
                       "Check the new event against the existing booking and contact the shopper.")
    detail_question = new_request and asks_booking_details(message)
    intent = None
    if new_request and not detail_question:
        intent = classify(message)
        detail_question = (intent == "booking_details" and can_read_booking(message)
                           and explicit_intent(message) is None)
    clarify = (new_request and not detail_question and intent in {"unknown", "complaint", "booking_details"}
               and not booking_concern(message) and not change_after_booking(message, case.accepted_start))
    if not new_request or detail_question or clarify:
        booking = tools.booking_status(case.case_id)
        if not matches_choice(case, booking) or not tools.notices.get(case.booking_reference):
            case.resolved_at = None
            return handoff(case, tools, "Unverified booking",
                           "Check the current booking and its confirmation before replying to the shopper.")
        if case.collection_scan_observed_at is not None:
            return case.reply(State.RESOLVED, shopper_message(case, "Collection on record"))
        if case.accepted_end and tools.now >= datetime.fromisoformat(case.accepted_end):
            return case.reply(State.RESOLVED, shopper_message(case, "No collection scan", window=case.accepted_window))
        if new_message and is_acknowledgement(case, message):
            return case.reply(State.RESOLVED, shopper_message(case, "Thanks") + " " + confirmed(case, booking))
        if clarify:
            lang = reply_language(message)
            prompt = language_help(lang, False, False) if lang else shopper_message(case, "Clarify booking")
            return case.reply(State.RESOLVED, confirmed(case, booking) + " " + prompt)
        return case.reply(State.RESOLVED, confirmed(case, booking))
    case.resolved_at = None
    owner = "Merchant Operations" if intent == "money" else "Support Operations"
    day = requested_day(message)
    if day and owner == "Support Operations":
        return handoff(case, tools, "Change confirmed booking",
                       f"Check whether {case.booking_reference} can be moved to {day}. Confirm "
                       "any change with the shopper.",
                       day=day, window=case.accepted_window)
    return handoff(case, tools, "Follow-up after booking",
                   "Review the new report against the existing booking and update the shopper.",
                   owner)


def changed_pending_booking(case, tools, message, selected_slot, changed_slot, classify):
    if changed_slot:
        case.note(f"shopper selected {selected_slot} while {case.accepted_slot} was pending")
    try:
        existing = tools.booking_status(case.case_id)
        if matches_choice(case, existing):
            case.booking_reference = existing["reference"]
            case.note(f"carrier booking {case.booking_reference}: {existing['window']}")
    except IncompleteCarrierRecord:
        case.note("carrier did not supply a readable booking reference")
    owner = "Merchant Operations" if message and classify(message) == "money" else "Support Operations"
    day = requested_day(message)
    if day and owner == "Support Operations":
        return handoff(case, tools, "Amendment under review",
                       f"Verify the existing pickup before requesting {day}. Confirm any change with the shopper.",
                       window=case.accepted_window, day=day)
    return handoff(case, tools, "Change pending booking",
                   "Check the original booking attempt and the shopper's latest request before changing "
                   "or confirming any visit.",
                   owner, window=case.accepted_window)


def check_request(case, tools, message, intent):
    if intent == "human":
        return handoff(case, tools, "Person requested",
                       "Read the shopper's message and contact them about the pickup.")
    if intent == "cancel":
        return handoff(case, tools, "Pickup declined",
                       "Check the existing pickup and confirm the shopper's preferred alternative before "
                       "changing anything.")
    if intent == "refund_status":
        return handoff(case, tools, "Refund status",
                       "Look up the refund timeline for this return and update the shopper.",
                       "Returns Support")
    pickup_intents = {"complaint", "pickup", "money", "courier_en_route", "repeat_miss", "address_change",
                      "already_collected", "partial_collection", "visit_update"}
    needs_clarification = intent not in pickup_intents
    if needs_clarification and (case.state == State.NEEDS_CLARIFICATION or (case.state == State.OPEN and message)):
        if case.state != State.NEEDS_CLARIFICATION or case.waiting_since is None:
            case.waiting_since = case.opened_at
        if case.email_expired(tools.now):
            return handoff(case, tools, "Missing shopper details",
                           "Contact the shopper to clarify the issue before changing the pickup.")
        return case.reply(State.NEEDS_CLARIFICATION, shopper_message(case, "Clarify pickup"))


def check_exceptions(case, tools, message, intent, record):
    if intent == "already_collected":
        case.support_reviewing_visit = True
        return handoff(case, tools, "Shopper reports collection",
                       "Check the collection scan and update the return record before arranging another pickup.")
    if intent == "visit_update":
        case.support_reviewing_visit = True
        return handoff(case, tools, "New pickup details",
                       "Check the shopper's update and who has the parcel before arranging a replacement.")
    if intent == "partial_collection":
        case.support_reviewing_visit = True
        return handoff(case, tools, "Partial collection",
                       "Match the parcels to their return and check the scans before scheduling another visit.")
    if intent == "address_change":
        return handoff(case, tools, "Shopper reports address change",
                       "Verify the corrected address with the shopper and carrier before issuing a fresh "
                       "offer.")
    if intent == "courier_en_route":
        return handoff(case, tools, "Courier on the way",
                       "Verify the current visit directly with the carrier and update the shopper before "
                       "offering another slot.")
    if record.get("commercial_exception"):
        return handoff(case, tools, "Merchant exception",
                       "Ask the merchant to approve the exception or an alternative, then inform the "
                       "shopper.",
                       "Merchant Operations")
    if intent == "money":
        reason = "Compensation requested" if "compensa" in message.casefold() else "Payment question"
        return handoff(case, tools, reason,
                       "Review the shopper's financial request with the merchant and reply with its "
                       "decision.",
                       "Merchant Operations")
    if "misses" in record and record["misses"] >= 2:
        case.support_reviewing_visit = True
        return handoff(case, tools, "Repeated carrier misses",
                       "Review the recorded attempts and agree a workable collection or alternative with "
                       "the shopper.",
                       count=record["misses"])
    if intent == "repeat_miss":
        case.support_reviewing_visit = True
        return handoff(case, tools, "Repeated shopper misses",
                       "Verify the reported multiple attempts with the carrier and agree the next step "
                       "with the shopper.")


def check_visit(case, tools, record):
    status = record["status"]
    if status == "customer_unavailable":
        attempted_at = record.get("attempted_at")
        if attempted_at:
            case.note(f"carrier-reported attempted visit at {attempted_at}")
        else:
            case.note("carrier marked shopper unavailable; time of the attempted visit was not provided")
        return handoff(case, tools, "Shopper marked unavailable",
                       "Compare the carrier's account with the shopper's message and obtain any missing "
                       "visit evidence.")
    if status == "collected":
        return handoff(case, tools, "Carrier reports collection",
                       "Check the collection scan against the shopper's account before arranging a new "
                       "visit.")
    if status not in {"unknown", "scheduled", "missed"}:
        return handoff(case, tools, "Unknown carrier status",
                       "Verify what the carrier status means before offering a slot or updating the "
                       "shopper.")
    booking = tools.booking_status(case.case_id)
    if booking is not None:
        return finish(case, tools, booking)
    if case.state in PENDING_CONFIRMATION:
        return handoff(case, tools, "Booking not verified",
                       "Trace the original booking attempt with the carrier before arranging another "
                       "visit.")
    if case.state == State.NEED_ADDRESS and record.get("missing_field") and case.email_expired(tools.now):
        return handoff(case, tools, "Address not verified",
                       "Check the missing address detail with the shopper and the carrier before "
                       "booking.")
    if record.get("missing_field"):
        field_name = record["missing_field"]
        case.note("carrier address validation flagged: " + field_name)
        case.note("simulated address prompt receipt: " + tools.alert_missing_detail(case.case_id, field_name))
        if case.state != State.NEED_ADDRESS:
            case.waiting_since = tools.now
        return case.reply(State.NEED_ADDRESS, shopper_message(case, "Address needed", field=field_name))
    if status != "missed":
        window_end = tools.local_time(datetime.fromisoformat(record["window_end"]))
        if tools.now < window_end:
            return case.reply(State.WINDOW_OPEN, shopper_message(case, "Original window", end=window_end))
        return waiting(case, tools)
    if record.get("misses") != 1:
        return handoff(case, tools, "Unknown number of misses",
                       "Confirm the number of missed attempts with the carrier before offering another "
                       "pickup.")
    if not tools.free_rebook_allowed(case.case_id):
        return handoff(case, tools, "Repeat pickup funding",
                       "Obtain the applicable approval and quote before asking the shopper to accept.",
                       "Merchant Operations")
    case.note("merchant approved the repeat pickup; no charge to shopper")


def decide(case, tools, message, selected_slot, offer_number, replay, classify):
    new_request = bool(message and not replay and not is_acknowledgement(case, message))
    changed_slot = selected_slot is not None and selected_slot != case.accepted_slot
    if case.state == State.RESOLVED:
        if changed_slot:
            case.note(f"ignored retired pickup option {selected_slot}; booking already confirmed")
        return after_confirmation(case, tools, message, not replay and bool(message), new_request, classify)
    if case.state == State.HUMAN_REVIEW:
        if selected_slot is not None:
            case.note(f"selection {selected_slot} received during human review at "
                      f"{tools.now.isoformat()}; no booking made")
        return update_open_review(case, tools, message if new_request else "")
    if case.state in PENDING_CONFIRMATION and (new_request or changed_slot):
        return changed_pending_booking(case, tools, message, selected_slot, changed_slot, classify)
    language = reply_language(message)
    choice = Reply() if language else read_choice(case, message)
    reader = read_intent if choice.discusses_offer or not new_request or asks_booking_details(message) else classify
    intent = ("unknown" if language else reader(message)) if message else None
    if case.offered and intent in {"unknown", "other", "pickup", "complaint"} and PICKUP_PRICING.search(message):
        intent = "money"
    reply = check_request(case, tools, message, intent)
    if reply is not None:
        return reply
    record = tools.lookup(case.case_id)
    case.carrier_observation = observed_visit(case, record, tools.now)
    case.note(f"carrier lookup at {tools.now.isoformat()}: {record['status']}, "
              f"scheduled window end {record['window_end']}, "
              f"recorded missed attempts: {record.get('misses', 'unknown')}")
    exception = check_exceptions(case, tools, message, intent, record)
    if exception is not None:
        return exception
    conflicting_button = selected_slot is not None and choice.slot != selected_slot
    unfamiliar_change = language and not simple_foreign_reply(message, language)
    if case.offered and new_request and (conflicting_button or booking_concern(message) or unfamiliar_change):
        return handoff(case, tools, "Offer withdrawn",
                       "Check the latest message and carrier evidence before issuing a fresh offer.")
    response = check_visit(case, tools, record)
    if response is not None:
        return response
    from_shopper = selected_slot is not None or new_request
    if case.offered and (case.email_expired(tools.now) or
                         (not from_shopper and not any(tools.accepts_pickup(t) for t in case.offered_starts.values()))):
        case.reply(State.AWAITING_REPLY, shopper_message(case, "Offer ended"))
    if case.state == State.AWAITING_REPLY:
        if from_shopper:
            return present_windows(case, tools, refresh=True)
        return case.reply(State.AWAITING_REPLY, case.last_reply)
    complaint = message if intent == "complaint" else None
    if case.offered and new_request and not choice.discusses_offer:
        return present_windows(case, tools, repeat_offer=True, choice=choice)
    return book_choice(case, tools, choice, selected_slot, offer_number, replay, complaint)


def book_choice(case, tools, choice, selected_slot, offer_number, replay, complaint):
    if selected_slot is None:
        if choice.slot is None or replay:
            return present_windows(case, tools, repeat_offer=choice.discusses_offer, complaint=complaint,
                                   choice=choice if choice.answer else None)
        selected_slot = choice.slot
        if choice.answer == "either":
            live = [slot for slot in choice.windows if tools.accepts_pickup(case.offered_starts[slot])]
            if not live:
                return present_windows(case, tools, choose_again=True)
            selected_slot = min(live, key=case.offered_starts.get)
        if choice.revision is not None:
            if offer_number is not None and offer_number != choice.revision:
                return present_windows(case, tools, choose_again=True)
            offer_number = choice.revision
    if (selected_slot not in case.offered or
            (offer_number if offer_number is not None else 1) != case.offer_number):
        return present_windows(case, tools, choose_again=True)
    case.accepted_slot = selected_slot
    case.accepted_window = case.offered[selected_slot]
    case.accepted_start = case.offered_starts[selected_slot].isoformat()
    case.accepted_end = case.offered_ends[selected_slot].isoformat()
    case.note(f"shopper explicitly accepted {selected_slot}: {case.offered[selected_slot]}")
    try:
        booking = tools.book_once(case.case_id, selected_slot, case.offered[selected_slot],
                                  case.offered_starts[selected_slot], case.offered_ends[selected_slot])
    except PermissionError:
        case.accepted_slot = case.accepted_window = case.accepted_start = case.accepted_end = None
        return handoff(case, tools, "Permission changed",
                       "Verify the current policy and obtain any required approval before making a new "
                       "offer.",
                       "Merchant Operations")
    except LostAcknowledgement:
        case.note("booking request sent; carrier acknowledgement missing")
        if not tools.supports_booking_lookup(case.case_id):
            return handoff(case, tools, "Carrier timeout",
                           "Check the original request with the carrier before creating or confirming "
                           "any pickup.",
                           window=case.accepted_window)
        return case.reply(State.BOOKING_UNCERTAIN, shopper_message(case, "Awaiting carrier reply"))
    except ValueError:
        case.accepted_slot = case.accepted_window = case.accepted_start = case.accepted_end = None
        return present_windows(case, tools, refresh=True)
    return finish(case, tools, booking)

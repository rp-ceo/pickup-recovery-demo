"""Stateful, in-process stand-ins for carrier, support and messaging APIs."""
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


BOOKING_LEAD = timedelta(minutes=30)


class TimeZoneConfigurationError(RuntimeError):
    pass


class LostAcknowledgement(Exception):
    pass


class IncompleteCarrierRecord(Exception):
    """The carrier response cannot safely support a scheduling decision."""


def carrier_time(value, field):
    try:
        if isinstance(value, str) and value.endswith("Z"):
            value = value[:-1] + "+00:00"
        timestamp = datetime.fromisoformat(value)
        if timestamp.utcoffset() is None:
            raise ValueError
        return timestamp.isoformat()
    except (TypeError, ValueError):
        raise IncompleteCarrierRecord(f"missing or invalid {field}") from None


class MockServices:
    def __init__(self, data=None):
        if data is None:
            data = json.loads(Path(__file__).with_name("fixtures.json").read_text(encoding="utf-8"))
        self.now = datetime.fromisoformat(data["clock"])
        self.window_end = data["window_end"]
        self.slots = data.get("slots") if isinstance(data.get("slots"), dict) else {}
        self.slot_starts = {}
        starts = data.get("slot_starts")
        if isinstance(starts, dict):
            for slot, value in starts.items():
                try:
                    self.slot_starts[slot] = datetime.fromisoformat(carrier_time(value, "slot start"))
                except IncompleteCarrierRecord:
                    self.slot_starts[slot] = None
        durations = data.get("slot_duration_minutes")
        self.slot_duration_minutes = durations if isinstance(durations, dict) else {}
        zone = data.get("slot_timezone")
        try:
            self.slot_timezone = ZoneInfo(zone)
        except (ZoneInfoNotFoundError, TypeError, ValueError):
            raise TimeZoneConfigurationError(
                f"Cannot load carrier time zone {zone!r}. Verify the zone name and install tzdata "
                "with this Python interpreter: python -m pip install tzdata (Windows: py -3 -m pip install tzdata)."
            ) from None
        self.now = self.local_time(self.now)
        self.cases = data["cases"]
        for record in self.cases.values():
            record.setdefault("window_end", self.window_end)
        self.merchant_policies = data["merchant_policies"]
        self.bookings = {}
        self.unacknowledged = set()
        self.inquiries = {}
        self.inquiry_updates = {}
        self.pending_inquiry_updates = {}
        self.callback_receipts = []
        self.window_updates = {}
        self.notices = {}
        self.notice_delivered_at = {}
        self.queue = {}
        self.calls = []
        self.notice_attempts = set()
        self.address_alerts = {}
        self.offer_receipts = {}

    def log(self, tool, case_id, detail):
        self.calls.append({"at": self.now.isoformat(), "tool": tool, "case": case_id, "result": deepcopy(detail)})

    def local_time(self, value):
        return value.astimezone(self.slot_timezone)

    def accepts_pickup(self, start):
        return start.astimezone(timezone.utc) - self.now.astimezone(timezone.utc) > BOOKING_LEAD

    def lookup(self, case_id):
        record = deepcopy(self.cases.get(case_id, {}))
        if not isinstance(record, dict):
            raise IncompleteCarrierRecord("unreadable pickup record")
        self.log("carrier.lookup", case_id, record.get("status") or "missing status")
        if not isinstance(record.get("status"), str) or not record["status"].strip():
            raise IncompleteCarrierRecord("missing pickup status")
        record["window_end"] = carrier_time(record.get("window_end"), "end of the pickup window")
        for field, description in (("attempted_at", "attempted visit time"), ("collected_at", "collection scan time")):
            if record.get(field) is not None:
                record[field] = carrier_time(record[field], description)
                if datetime.fromisoformat(record[field]) > self.now:
                    raise IncompleteCarrierRecord(f"{description} is in the future")
        if record.get("collected_at") and record["status"] != "collected":
            raise IncompleteCarrierRecord(
                f"collection at {record['collected_at']} conflicts with status {record['status']}")
        misses = record.get("misses")
        if "misses" in record and (type(misses) is not int or misses < 0):
            raise IncompleteCarrierRecord("invalid count of missed pickups")
        missing_field = record.get("missing_field")
        if missing_field is not None and (not isinstance(missing_field, str) or not missing_field.strip()):
            raise IncompleteCarrierRecord("invalid missing address detail")
        return record

    def offer_slots(self, case_id):
        ids = self.cases[case_id].get("slots", list(self.slots))
        if not isinstance(ids, list) or any(not isinstance(slot, str) or slot not in self.slots for slot in ids):
            self.log("carrier.available_slots", case_id, "invalid slot list")
            raise IncompleteCarrierRecord("invalid replacement slot list")
        result = {}
        for slot in ids:
            try:
                start, end = self.slot_interval(slot)
                if (start.minute or start.second or start.microsecond or
                        (start.hour, end.hour) not in {(8, 12), (12, 16), (16, 20)} or
                        end.date() != start.date() or end.minute or end.second or end.microsecond):
                    raise IncompleteCarrierRecord("unsupported pickup range")
                day = start.strftime("%a %d %b, %H:%M")
                if start.date() == end.date() and start.utcoffset() == end.utcoffset():
                    label = f"{day}–{end:%H:%M %Z}"
                else:
                    label = f"{day} {start:%Z}–{end:%a %d %b, %H:%M %Z}"
                if self.slots[slot] != label:
                    raise IncompleteCarrierRecord("slot label does not match its time interval")
                if self.accepts_pickup(start):
                    result[slot] = label
            except IncompleteCarrierRecord as error:
                self.log("carrier.reject_slot", case_id, {"slot": slot, "reason": str(error)})
        self.log("carrier.available_slots", case_id, result)
        return result

    def slot_interval(self, slot):
        start = self.slot_starts.get(slot)
        duration = self.slot_duration_minutes.get(slot)
        if not isinstance(start, datetime) or start.utcoffset() is None or type(duration) is not int or duration <= 0:
            raise IncompleteCarrierRecord("missing or invalid slot start or duration")
        try:
            end = start.astimezone(timezone.utc) + timedelta(minutes=duration)
            return start.astimezone(self.slot_timezone), end.astimezone(self.slot_timezone)
        except (OverflowError, ValueError):
            raise IncompleteCarrierRecord("invalid slot interval") from None

    def inquire(self, case_id, wait):
        if case_id not in self.inquiries:
            self.inquiries[case_id] = (f"Q-{case_id}", self.now)
            self.log("carrier.ask_for_update", case_id, self.inquiries[case_id][0])
        inquiry, started = self.inquiries[case_id]
        if self.now < started + wait:
            self.pending_inquiry_updates.setdefault(inquiry, started + wait)
        return inquiry, started

    def send_inquiry_update(self, case_id, message, offer_number=None):
        inquiry, _ = self.inquiries[case_id]
        if inquiry in self.pending_inquiry_updates:
            if offer_number is not None and self.cases[case_id].get("offer_delivery_fails"):
                self.log("support.send_inquiry_update", case_id, "replacement options could not be delivered")
                return None
            due = self.pending_inquiry_updates.pop(inquiry)
            self.inquiry_updates[inquiry] = message
            self.log("support.send_inquiry_update", case_id, message)
            receipt = {"case_id": case_id, "inquiry": inquiry, "due_at": due.isoformat(),
                       "delivered_at": self.now.isoformat(), "overdue": self.now > due,
                       "minutes_late": max(0, (self.now - due).total_seconds() / 60)}
            self.callback_receipts.append(receipt)
            self.log("support.callback_receipt", case_id, receipt)
            if offer_number is not None:
                offer_receipt = f"CALLBACK-OFFER-{case_id}-{offer_number}"
                self.offer_receipts[case_id, offer_number] = offer_receipt
                return offer_receipt

    def send_window_update(self, case_id, message):
        inquiry, _ = self.inquiries[case_id]
        if inquiry not in self.window_updates:
            receipt = None if self.cases[case_id].get("window_update_fails") else f"UPDATE-{inquiry}"
            self.window_updates[inquiry] = receipt
            self.log("support.send_window_update", case_id, {"message": message, "delivery_receipt": receipt})
        return self.window_updates[inquiry]

    def supports_booking_lookup(self, case_id):
        return self.cases[case_id].get("attempt_lookup") is True

    def booking_status(self, case_id):
        if case_id in self.unacknowledged and not self.supports_booking_lookup(case_id):
            return None
        booking = self.bookings.get(case_id)
        if booking is not None and not isinstance(booking, dict):
            raise IncompleteCarrierRecord("unreadable booking confirmation")
        tool = "carrier.find_by_attempt" if case_id in self.unacknowledged else "support.check_booking_receipt"
        self.log(tool, case_id, booking.get("reference", "missing reference") if booking else "none")
        return booking

    def free_rebook_allowed(self, case_id):
        record = self.cases[case_id]
        merchant = record.get("merchant")
        policy = self.merchant_policies.get(merchant) if isinstance(merchant, str) else None
        fee = record.get("replacement_fee_cents")
        terms = policy if isinstance(policy, dict) else {}
        quote = record.get("carrier_quote_eur_cents")
        limit = terms.get("max_repeat_eur_cents")
        covered = type(quote) is int and type(limit) is int and 0 <= quote <= limit
        permitted = (terms.get("free_rebooking_approved") is True and
                     terms.get("repeat_charge_payer") in ("merchant", "carrier") and covered and
                     type(fee) is int and fee == 0 and not record.get("commercial_exception"))
        self.log("merchant.check_rebooking_permission", case_id,
                 {"approved": permitted, "payer": terms.get("repeat_charge_payer"),
                  "shopper_fee_cents": fee, "carrier_quote_eur_cents": quote, "max_repeat_eur_cents": limit})
        return permitted

    def book_once(self, case_id, slot, expected_window, expected_start, expected_end):
        existing = self.bookings.get(case_id)
        if existing:
            if case_id in self.unacknowledged:
                raise LostAcknowledgement()
            if slot != existing["slot"]:
                raise ValueError("A different replacement already exists.")
            return existing
        record = self.lookup(case_id)
        if record["status"] != "missed" or record.get("misses") != 1 or record.get("missing_field"):
            raise IncompleteCarrierRecord("cannot verify a first missed pickup at booking time")
        if not self.free_rebook_allowed(case_id):
            raise PermissionError("Free autonomous rebooking is no longer authorized.")
        available = self.offer_slots(case_id)
        if (slot not in available or available[slot] != expected_window or self.slot_starts[slot] != expected_start
                or self.slot_interval(slot)[1] != expected_end):
            raise ValueError("This slot is no longer available.")
        booking = {"reference": f"BK-{case_id}", "slot": slot, "window": available[slot],
                   "start": self.slot_starts[slot].isoformat(), "end": self.slot_interval(slot)[1].isoformat()}
        start, end = self.slot_interval(slot)
        self.log("support.prepare_repickup", case_id,
                 {"repickup_attempt": 1, "pickup_ranges": [f"RANGE_{start.hour}_TO_{end.hour}"]})
        self.bookings[case_id] = booking
        if self.cases[case_id].get("booking_timeout"):
            self.unacknowledged.add(case_id)
            self.log("carrier.book_once", case_id, "No reply received")
            raise LostAcknowledgement()
        self.log("carrier.book_once", case_id, booking["reference"])
        return booking

    def notify_once(self, case_id, booking):
        reference = booking["reference"]
        if reference in self.notices:
            return self.notices[reference]
        failure = self.cases[case_id].get("notice_failure")
        if failure == "persistent" or (failure is True and reference not in self.notice_attempts):
            self.notice_attempts.add(reference)
            self.log("support.notify", case_id, "delivery failed")
            return None
        receipt = "NOTICE-" + reference
        self.notices[reference] = receipt
        self.notice_delivered_at[reference] = self.now
        self.log("support.notify", case_id, receipt)
        return receipt

    def handoff(self, case_id, owner, reason, next_step, evidence):
        self.queue[case_id] = {"owner": owner, "reason": reason, "next_step": next_step, "evidence": list(evidence)}
        self.log("support.handoff", case_id, owner)

    def update_review(self, case_id, evidence, observation, next_step):
        task = self.queue[case_id]
        task["evidence"] = list(evidence)
        task["latest_carrier_record"] = dict(observation)
        task["next_step"] = next_step
        self.log("support.update_existing_case", case_id, {
            "owner": task["owner"], "latest_carrier_record": observation, "next_step": next_step, "evidence": evidence})

    def send_offer_once(self, case_id, offer_number, message):
        key = (case_id, offer_number)
        if key in self.offer_receipts:
            return self.offer_receipts[key]
        receipt = None if self.cases[case_id].get("offer_delivery_fails") else f"OFFER-{case_id}-{offer_number}"
        self.offer_receipts[key] = receipt
        self.log("support.send_pickup_options", case_id, {"message": message, "delivery_receipt": receipt})
        return receipt

    def alert_missing_detail(self, case_id, field_name):
        key = (case_id, field_name)
        if key not in self.address_alerts:
            self.address_alerts[key] = f"ADDR-{case_id}-{len(self.address_alerts)+1}"
            self.log("support.address_alert", case_id, self.address_alerts[key])
        return self.address_alerts[key]

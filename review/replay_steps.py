EVENTS = {
    "carrier_event": ("carrier", "Carrier alert"),
    "shopper_message": ("shopper", "Shopper email"),
    "shopper_selection": ("shopper", "Shopper selects a window"),
    "timer": ("timer", "Scheduled check"),
}

STATUS = {
    "missed": "Missed pickup",
    "unknown": "No confirmed outcome",
    "customer_unavailable": "Marked unavailable",
    "scheduled": "Scheduled",
    "collected": "Collected",
}


def check_step(calls, turn):
    facts = []

    def add(label, value):
        facts.append({"label": label, "value": value})

    status = calls.get("carrier.lookup")
    if status:
        add("Carrier record", STATUS.get(status, status))
    policy = calls.get("merchant.check_rebooking_permission")
    if policy:
        if not policy["approved"]:
            add("Repeat pickup", "Approval missing")
        elif policy.get("shopper_fee_cents") == 0 and policy.get("payer"):
            add("Repeat pickup", f"No charge to the shopper · {policy['payer']} pays")
        else:
            add("Repeat pickup", "Check the payer and shopper fee")
    if "carrier.available_slots" in calls:
        add("Available windows", str(len(calls["carrier.available_slots"])))
    if "carrier.ask_for_update" in calls:
        add("Carrier inquiry", calls["carrier.ask_for_update"])
    booking = calls.get("carrier.book_once") or calls.get("carrier.find_by_attempt")
    if booking:
        add("Carrier reply", booking)
    existing = calls.get("support.check_booking_receipt")
    if existing and existing != "none" and not booking:
        add("Existing booking", existing)
    handoff = calls.get("support.handoff") or calls.get("support.update_existing_case")
    if handoff:
        title = f"{turn['owner']} takes over" if "support.handoff" in calls else "Update the open case"
        return "support", title, turn["next_step"], facts
    if "carrier.ask_for_update" in calls:
        return "checks", "Ask the carrier what happened", "The carrier has an open inquiry about the original visit.", facts
    if "carrier.find_by_attempt" in calls:
        return "checks", "Check the original booking attempt", "This simulated carrier supports a lookup by attempt.", facts
    if "carrier.book_once" in calls:
        return "checks", "Request the new pickup", "The agent rechecks the window and merchant terms before booking.", facts
    if policy:
        return "checks", "Check the fee and pickup times", "The agent checks who pays and which windows the carrier can offer.", facts
    if "support.check_booking_receipt" in calls or status:
        return "checks", "Check the pickup record", "", facts
    return None


def response_step(turn, calls):
    message = turn["message"]
    notice = calls.get("support.notify")
    if notice:
        if notice == "delivery failed":
            return "record", "Confirmation delivery failed", message, None
        return "agent", "The shopper gets confirmation", message, notice
    callback = calls.get("support.callback_receipt")
    if callback:
        return "agent", "Shopper update delivered", calls["support.send_inquiry_update"], None
    for operation, title in (("support.send_pickup_options", "Send the shopper new times"),
                             ("support.send_window_update", "Shopper update delivered")):
        attempt = calls.get(operation)
        if attempt:
            receipt = attempt.get("delivery_receipt")
            if receipt:
                return "agent", title, attempt["message"], receipt
            return "record", "Message delivery failed", message, None
    if calls.get("support.address_alert"):
        return "agent", "Address detail requested", message, calls["support.address_alert"]
    if turn["event_source"] in ("shopper_message", "shopper_selection"):
        title = "Promise a follow-up time" if turn["state"] == "WAITING_CARRIER" else "Agent reply"
        return "agent", title, message, None
    return "record", "Case update", message, None


def replay_steps(case):
    steps = []
    for index, turn in enumerate(case["turns"]):
        calls = {c["tool"]: c["result"] for c in turn["tool_calls"]}

        def add(kind, title, text, facts=None, receipt=None):
            steps.append({"turn": index, "at": turn["at"], "kind": kind, "title": title,
                          "text": text, "facts": facts or [], "receipt": receipt})

        kind, title = EVENTS[turn["event_source"]]
        if (kind == "carrier" and turn["state"] == "OFFERED" and index > 0
                and case["turns"][index - 1]["state"] == "OFFERED" and "support.send_pickup_options" not in calls):
            add(kind, "The existing offer stays open", turn["event"],
                [{"label": "Shopper inbox", "value": "No second offer sent"}])
            continue
        if (kind == "carrier" and index == 0 and "support.send_pickup_options" in calls
                and calls.get("carrier.lookup") == "missed"):
            title = "The carrier reports a missed visit"
        elif kind == "shopper" and index == 0 and "carrier.ask_for_update" in calls:
            title = "The shopper asks about the visit"
        elif turn["event_source"] == "shopper_message" and "support.prepare_repickup" in calls:
            title = "The shopper picks a time"
        add(kind, title, turn["event"])
        check = check_step(calls, turn)
        if check:
            add(*check)
            carrier_requests = ("carrier.ask_for_update", "carrier.book_once", "carrier.find_by_attempt")
            if check[0] == "checks" and any(tool in calls for tool in carrier_requests):
                steps[-1]["destination"] = "Carrier"
        kind, title, text, receipt = response_step(turn, calls)
        add(kind, title, text, receipt=receipt)
    return steps

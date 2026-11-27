EVENTS = {
    "carrier_event": ("carrier", "Carrier update", "carrier_record"),
    "shopper_message": ("shopper", "Shopper email", "email"),
    "shopper_selection": ("shopper", "Shopper selects a window", "link"),
    "timer": ("timer", "Scheduled check", "internal"),
}

STATUS = {
    "missed": "Missed pickup",
    "unknown": "No confirmed outcome",
    "customer_unavailable": "Marked unavailable",
    "scheduled": "Scheduled",
    "collected": "Collected",
}


def fact(label, value):
    return {"label": label, "value": value}


def pickup_facts(calls):
    facts = []
    if "carrier.lookup" in calls:
        status = calls["carrier.lookup"]
        facts.append(fact("Carrier record", STATUS.get(status, status)))
    if "merchant.check_rebooking_permission" in calls:
        policy = calls["merchant.check_rebooking_permission"]
        if not policy["approved"]:
            terms = "Free rebooking has no approval"
        elif policy.get("shopper_fee_cents") == 0 and policy.get("payer") in ("merchant", "carrier"):
            terms = f"No charge to the shopper · {policy['payer']} pays"
        else:
            terms = "Shopper fee or payer needs verification"
        facts.append(fact("Repeat pickup", terms))
    if "carrier.available_slots" in calls:
        facts.append(fact("Available windows", str(len(calls["carrier.available_slots"]))))
    existing = calls.get("support.check_booking_receipt")
    if existing and existing != "none":
        facts.append(fact("Existing booking", existing))
    return facts


def evidence_value(turn, prefix):
    for entry in reversed(turn["evidence"]):
        if entry.startswith(prefix):
            return entry[len(prefix):]
    return ""


def replay_steps(case):
    steps = []
    for index, turn in enumerate(case["turns"]):
        calls = {call["tool"]: call["result"] for call in turn["tool_calls"]}

        def add(kind, title, text, channel="internal", facts=None, receipt=None, destination=None):
            step = {"turn": index, "at": turn["at"], "kind": kind, "channel": channel,
                    "title": title, "text": text, "facts": facts or [], "receipt": receipt}
            if destination:
                step["destination"] = destination
            steps.append(step)

        kind, title, channel = EVENTS[turn["event_source"]]
        if (kind == "carrier" and index > 0 and turn["state"] == case["turns"][index - 1]["state"] == "OFFERED"
                and "support.send_pickup_options" not in calls):
            add(kind, "The existing offer stays open", turn["event"], channel,
                [fact("Shopper inbox", "No second offer sent")])
            continue
        if kind == "carrier" and calls.get("carrier.lookup") == "missed" and index == 0:
            if "support.send_pickup_options" in calls:
                title = "The carrier reports a missed visit"
        elif kind == "shopper" and "carrier.ask_for_update" in calls:
            title = "The shopper asks about the visit"
        elif kind == "shopper" and "support.prepare_repickup" in calls:
            title = "The shopper picks a time"
        add(kind, title, turn["event"], channel)

        facts = pickup_facts(calls)
        if "carrier.book_once" in calls:
            selection = evidence_value(turn, "shopper explicitly accepted ")
            chosen = [fact("Shopper's choice", selection)] if selection else []
            add("checks", "Request the new pickup", "The agent rechecks the fee and availability, then submits the chosen window.",
                "carrier_request", chosen, destination="Carrier")
        elif "carrier.find_by_attempt" in calls:
            add("checks", "Check the original booking attempt", "This carrier supports looking up the earlier request.",
                "carrier_request", destination="Carrier")
        elif "carrier.ask_for_update" in calls:
            facts.append(fact("Inquiry reference", calls["carrier.ask_for_update"]))
            add("checks", "Ask the carrier what happened", "The agent opens one inquiry about the original visit.",
                "carrier_request", facts, destination="Carrier")
        elif "carrier.available_slots" in calls and calls["carrier.available_slots"]:
            if calls.get("carrier.lookup") == "missed":
                remaining = [item for item in facts if item["label"] != "Carrier record"]
                add("checks", "Carrier record confirms the missed pickup", "", facts=remaining)
            else:
                add("checks", "Check the available pickup times", "", facts=facts)
        elif facts:
            add("checks", "Check the pickup record", "", facts=facts)

        response_recorded = False
        for call in turn["tool_calls"]:
            tool, result = call["tool"], call["result"]
            if tool in ("carrier.book_once", "carrier.find_by_attempt"):
                if result in ("No reply received", "none", "missing reference"):
                    add("record", "Booking still unconfirmed", "There is no confirmed reference for this request.")
                else:
                    info = [fact("Booking reference", result)]
                    window = evidence_value(turn, f"carrier booking {result}: ")
                    if window:
                        info.append(fact("Confirmed pickup", window))
                    title = "Pickup booked" if tool == "carrier.book_once" else "Existing booking found"
                    add("carrier", title, "", "carrier_response", info,
                        destination="Pickup agent")
            elif tool in ("support.handoff", "support.update_existing_case"):
                title = f"{turn['owner']} takes over" if tool == "support.handoff" else "Update the open case"
                add("support", title, turn["next_step"], destination=turn["owner"])
            elif tool in ("support.send_pickup_options", "support.send_window_update"):
                response_recorded = True
                if result["delivery_receipt"]:
                    title = "Send the shopper new times" if tool == "support.send_pickup_options" else "Shopper update delivered"
                    add("agent", title, result["message"], "email", receipt=result["delivery_receipt"])
                else:
                    add("record", "Message delivery failed", "The shopper did not receive this message.")
            elif tool == "support.address_alert":
                response_recorded = True
                add("agent", "Address detail requested", turn["message"], "email", receipt=result)
            elif tool == "support.notify":
                response_recorded = True
                if result == "delivery failed":
                    add("record", "Confirmation delivery failed", turn["message"])
                else:
                    add("agent", "The shopper gets confirmation", turn["message"], "email", receipt=result)
            elif tool == "support.callback_receipt":
                response_recorded = True
                add("agent", "Shopper update delivered", calls["support.send_inquiry_update"], "email")

        if not response_recorded:
            if turn["event_source"] in ("shopper_message", "shopper_selection"):
                title = "Agent reply"
                if turn["state"] == "WAITING_CARRIER":
                    title = "Promise a follow-up time"
                elif turn["state"] == "OFFERED" and calls.get("carrier.available_slots"):
                    title = "Reply with pickup options"
                add("agent", title, turn["message"], channel)
            else:
                add("record", "Case update", turn["message"])
    return steps

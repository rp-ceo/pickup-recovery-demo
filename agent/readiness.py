from dataclasses import asdict, dataclass, replace


@dataclass(frozen=True)
class Visit:
    stage: str
    required_detail: str = ""
    detail_on_file: bool = False
    request_sent: bool = False
    detail_disputed: bool = False


@dataclass(frozen=True)
class Decision:
    action: str
    title: str
    note: str


def check_visit(visit):
    if visit.stage == "collected":
        return Decision("close", "Collection recorded", "The carrier supplied a collection scan. No further pickup is due.")
    if visit.stage == "route_exception":
        return Decision("carrier_ops", "Send the route exception to Carrier Operations",
                        "Check the affected route with the depot and give the shopper a time for an update.")
    if visit.stage == "confirmed_miss":
        return Decision("recover", "Start missed-pickup recovery",
                        "The first visit has already failed. Check the return and merchant terms before offering new times.")
    if visit.stage == "dispatched":
        if visit.required_detail and not visit.detail_on_file:
            return Decision("carrier_ops", "Ask the depot if the driver can use an update",
                            "The van has left. Support needs carrier confirmation before promising a change.")
        return Decision("wait", "Keep the scheduled visit", "The driver has left. Wait for a carrier update.")
    if visit.stage != "scheduled":
        return Decision("check_status", "Verify the carrier status",
                        "Support checks the unfamiliar status before changing the visit or messaging the shopper.")
    if not visit.required_detail or visit.detail_on_file:
        return Decision("wait", "Keep the scheduled visit", "No detail is outstanding. The shopper gets no extra message.")
    if visit.detail_disputed:
        return Decision("verify_address", "Have Support check the address flag",
                        "The shopper says this detail does not apply. Verify the requirement and keep the scheduled visit.")
    if visit.request_sent:
        return Decision("await_detail", "Wait for the requested detail",
                        "One request is already open for this return. Keep the existing visit and wait for a reply.")
    return Decision("ask", "Ask for the missing detail",
                    f"Could you confirm {visit.required_detail} in the return portal, or tell us if it does not apply?")


STAGES = {
    "scheduled": "Scheduled · before dispatch", "dispatched": "Driver dispatched",
    "route_exception": "Depot reported a route disruption", "confirmed_miss": "Carrier confirmed a missed visit",
    "collected": "Collection scan received",
}
SCENARIOS = {
    "entrance": ("Building entrance missing", Visit("scheduled", "the building entrance")),
    "complete": ("Address already complete", Visit("scheduled", "the building entrance", True)),
    "house": ("No apartment detail required", Visit("scheduled")),
    "dispatched": ("Driver has already left", Visit("dispatched", "the building entrance")),
    "route": ("Carrier route disrupted", Visit("route_exception")),
    "missed": ("First visit missed", Visit("confirmed_miss")),
    "scan": ("Parcel already collected", Visit("collected")),
}


def example(name):
    label, visit = SCENARIOS[name]
    if visit.required_detail:
        address = ("Supplied" if visit.detail_on_file else "Flagged by merchant") + " · " + visit.required_detail
    else:
        address = "No missing detail flagged"
    decision = check_visit(visit)
    result = {"label": label, "stage": STAGES[visit.stage], "address": address, "decision": asdict(decision)}
    if decision.action == "ask":
        requested = replace(visit, request_sent=True)
        result["updated_address"] = "Supplied by shopper · " + visit.required_detail
        result["followup"] = {
            "pending": asdict(check_visit(requested)),
            "updated": asdict(check_visit(replace(requested, detail_on_file=True))),
            "disputed": asdict(check_visit(replace(requested, detail_disputed=True))),
            "left": asdict(check_visit(replace(requested, stage="dispatched"))),
        }
    return result

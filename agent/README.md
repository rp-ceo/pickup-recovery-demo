# Pickup recovery

The first argument selects a fictional return record. With no extra arguments the runner replays the fixture's conversation. Supply a message to try a different conversation from the same starting facts. Times advance on a simulated clock.

Install the time-zone data from the project root first (Windows: `py -3 -m pip install -r requirements.txt`. macOS/Linux: `python3 -m pip install -r requirements.txt`). Then run the following from the agent directory, using `py -3` on Windows.

```sh
python3 demo.py --readiness entrance
python3 demo.py P101 --reply "Thursday works for me"
python3 demo.py P101 --reply "Please book Thursday" --after-booking "What time is my pickup again?"
python3 demo.py P101 --reply-after 15 --reply "Thu pls"
python3 demo.py P101 --message "El mensajero no vino"
python3 demo.py P101 --message "The courier did come and collect it, thanks"
python3 demo.py P102 --advance 30
python3 demo.py P112
python3 demo.py P114
python3 -m unittest discover
```

| Example | Decision to inspect |
| --- | --- |
| Thursday email (P101) | Match a single current option and recheck permission and availability before booking. |
| Carrier silence (P102) | Open one inquiry. Update the shopper at the deadline and give the unresolved case to Support. |
| Lost reply (P107) | Default to carrier reconciliation by Support. The simulated carrier may already hold the booking. |
| Window still open (P112) | Recheck when the original window ends. If the carrier stays silent, follow up at the inquiry deadline. |
| An unclear email (P129) | With two choices, ask which one. A reply the next morning can still select an available visit. |
| Change to Thursday (P114) | Warn that the original Wednesday appointment could still happen. Keep one case and one booking attempt until its status is known. |
| Old address (P117) | Withdraw the offer when the shopper disputes the address. An old selection must not dispatch a courier. |
| Carrier writes first (P118) | Notify the shopper after a verified miss. A repeated alert sends no second offer.  |
| Collection after handoff (P127) | Record the scan on the staff-owned case, along with the time the scan arrived. |
| Known payer missing (P134) | Refer the decision to Merchant Operations before requesting another paid service. |

## When an email arrives

Read the current reply in the context of the open offer or confirmed visit. A unique choice can authorise the chosen time. A question gets an answer, an unclear preference gets a clarification, and a concern about the parcel or address goes to a person before another booking. A confirmed appointment can be looked up again without another booking request. Common French and Catalan scheduling replies receive a short prompt in that language to use the link or continue in English or Spanish. Uncertain changes need review. The prototype has no general multilingual interpreter.

Shoppers have up to 48 hours. Check each option against current carrier availability and the 30-minute lead time. An expired option cannot select a different day. If the carrier issues a revised offer, its link or the option code printed in that email ties the selection to the right revision. Once the offer expires, check what the carrier can offer before asking for a fresh selection. The carrier inquiry and confirmation messages use separate deadlines. In the example above, `--reply-after 15` advances the clock by 15 hours before the email arrives.

## How the decision is made

- [email_reply.py](email_reply.py) extracts the shopper's current text from a plain-text email, keeping new caveats. [choices.py](choices.py) matches an explicit selection against the current offer. [intent.py](intent.py) checks the shopper's meaning and flags custody or address changes. The full original message stays in the event trace.
- [pickup.py](pickup.py) keeps the current offer, shopper consent, carrier evidence and booking status together. A carrier event, shopper reply or timer goes through the same case.
- [carrier.py](carrier.py) simulates the logistics record, carrier booking, store agreement, notification receipts and Support queue. The shopper fee and the carrier quote are separate. The euro-only simulation compares the quote with the merchant agreement before offering and again before booking. Actual carrier invoices belong in the pilot cost calculation. Dates in the fixtures represent the pilot carrier's hypothetical availability.
- [demo.py](demo.py) advances time and runs the events in [fixtures.json](fixtures.json). From the repository root, run `python3 review/build_view.py` to rebuild the offline viewer.

## Language model

With a model already installed and served by Ollama on this machine, try an indirect address correction:

```sh
python3 demo.py P101 --message "The buzzer on file points to where I used to live." --ollama-model MODEL_NAME --json
```

Replace `MODEL_NAME` with the installed model's name. Clear choices, explicit safety checks and recognised examples take the same route in both modes. For an unresolved reply, [local_model.py](local_model.py) asks the model for one category. Check `model_calls` to see whether a response was classified, unresolved, invalid or unavailable. An empty count means this case needed no model call. The model cannot select a slot, store a new address or approve a fee.

Tests use supplied responses and a simulated outage. Those tests check the integration. Accuracy and cost on actual shopper emails require a labelled pilot sample.

## What the simulation can establish

Tests check the policy against fictional cases, including duplicate events, stale choices and replies that arrive after a booking. The simulation exercises deadlines when its clock advances. It has no always-on worker, process restart recovery, live carrier connection or delivery channel. The mock peak-volume run checks outcomes under two event counts. It cannot measure live response times, carrier limits or realised savings.

Before connecting a merchant, validate its contract and supported range/date combinations with the carrier, save booking attempts durably, reconcile any uncertain attempt, deduplicate carrier events and assign an owner to overdue updates. The default path does not depend on an attempt-specific lookup. One explicitly labelled optional example models a carrier that offers one. [REVER's pickup request](https://docs.itsrever.com/apis/admin/logistics/createpickup) · [Return logistics summary](https://docs.itsrever.com/apis/admin/logistics/getreversedeliveryinfo)

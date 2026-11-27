# When a courier misses a return pickup

The shopper still has the parcel and has to ask the store what to do. After a verified miss, send the shopper new pickup options before they need to contact support. An email reply or a link can select an eligible replacement. If the carrier cannot confirm the visit, keep the request open and tell the shopper who will check it.

[Open the pickup replay in your browser](https://rp-ceo.github.io/pickup-recovery-demo/review/Pickup_Operations.html). For offline use, [download the demo and source](https://github.com/rp-ceo/pickup-recovery-demo/archive/refs/heads/main.zip), extract the ZIP and open `review/Pickup_Operations.html`. Start with the carrier alert. The other two featured cases show an unclear email and a lost booking reply. All orders, appointments and messages in the demo are fictional.

## What changes for the shopper

1. A carrier reports a failed pickup, or a shopper writes first. Read the linked return. When the original window ends without a carrier update, open one inquiry. Tell the shopper when they will hear back, even if the carrier is still silent.
2. For a verified first miss, check the address, current availability and merchant terms. Offer a no-charge pickup only when the shopper owes nothing, the payer is known and the carrier quote fits the approved limit. Check the price again when booking.
3. Send a link and accept an unambiguous reply to the current offer, such as “Thursday works for me”. If the shopper has taken the parcel to a drop-off point, reports a partial collection, or a collection timestamp conflicts with the carrier status, withdraw the offer and ask Support to check who has the parcel.
4. Request the selected visit once. Send confirmation after the carrier accepts that appointment. An uncertain request goes to Support. The requested replacement may already be booked. Support checks it before arranging anything else.
5. A delivered confirmation resolves the scheduling question. A later carrier scan verifies the physical collection. Both matter.

For an ordinary unclear reply, keep the current link usable and ask which time the shopper meant. A question can show the available times without booking. If two dates are explicitly acceptable, use the earlier available visit; a single rejected date gives the shopper an alternative to confirm. Evidence of a custody, address or payment problem stops booking.

The pilot gives the shopper up to 48 hours to reply. Each individual slot closes 30 minutes before its start or earlier if the carrier withdraws it. The other offered times can still be used. After expiry, check availability and get fresh consent before booking. A carrier inquiry has a separate 30-minute update promise.

## Where language interpretation earns its cost

A failed-pickup event and a link can handle the straightforward case on their own. The open question is how many shoppers reply by email with a change, a question or several facts at once. A reply such as “Thursday works, but the courier just picked it up” should stop a booking.

The offline demo uses English and Spanish rules and a small set of labelled examples. It reads choices from the current email and can answer a question about an existing booking after checking its record and confirmation. An optional local language model suggests a category for replies the rules leave unresolved. An unavailable model leaves those replies open for clarification or review. Booking, charges and availability always use the same checks.

To measure what the model adds, have Support label unseen, anonymised emails before comparing the same reply workflow with and without the model. Score the final routing decision by language, unsafe actions, avoidable handoffs and cost per additional resolution. Count model outages separately. The comparison between the link and the link plus email rules measures the value of handling replies as a whole.

## REVER and the pilot carrier

A “Pick up failed” event can already open or update a Gorgias ticket for a connected merchant. The merchant would explain the link and email reply in its original pickup confirmation. Contact the shopper proactively only after verifying the miss. [REVER's Gorgias integration](https://docs.itsrever.com/guides/gorgias-integration)

The pickup API accepts preferred ranges of 08:00–12:00, 12:00–16:00 and 16:00–20:00, or no preference. It requires an existing logistics order and a supported provider/carrier. Its public request does not specify a calendar day. A pilot needs a separate agreement or carrier service for date availability and confirmation. Check returned details against the shopper's selection before making a promise. [CreatePickup](https://docs.itsrever.com/apis/admin/logistics/createpickup)

The logistics summary can return a pickup reference for a return. It does not document a lookup for an individual failed request or a safe amendment of a confirmed visit. For some providers, increasing `repickup_attempt` bypasses a duplicate guard to create a genuine new collection. Never increment it just because a response timed out. [Return logistics](https://docs.itsrever.com/apis/admin/logistics/getreversedeliveryinfo) · [Repeat-attempt field](https://docs.itsrever.com/apis/admin/logistics/createpickup)

## What the pilot could save

For illustration, assume one merchant schedules 10,000 home pickups a month and the carrier confirms 500 misses (5%). The table uses assumed staffed contacts per verified miss. Replace these rates with merchant data before deciding on an investment.

| Monthly flow | Staffed contacts per miss | Staffed contacts | Handling cost at €4 per contact |
| --- | ---: | ---: | ---: |
| A. Current handling | 0.90 | 450 | €1,800 |
| B. Proactive email with a rebooking link | 0.60 | 300 | €1,200 |
| C. Same email and link, plus reply handling | 0.45 | 225 | €900 |

The link would save 150 contacts and free €600 of staff time per month. Handling replies would save a further 75 contacts and free €300. Together that is €900, or 37.5 hours at 10 minutes per contact and €24 per staff hour. These figures describe capacity that could be redeployed. The language model has no measured savings in this estimate.

Compare the additional cost of each step with the staff time it releases. Count message delivery, monitoring, extra human work and any carrier charges above what the previous flow incurred. Account for setup separately. If the link works and the extra email handling costs more than €300 a month in this example, keep the link on its own. If the merchant already sends the same proactive link, measure that existing flow as the baseline and give the link no new savings credit.

## Pilot decision

Start with four weeks of data for one merchant and one carrier. Join scheduled pickups, verified misses, support contacts, staff time, promised updates, carrier invoices and collection scans on the return ID. This gives the home-pickup share, miss rate, contacts per miss and actual fee payer.

Where feasible, assign comparable returns concurrently to A, B and C. Measure B against A for the proactive email and link, and C against B for the reply workflow. Use the same eligibility rules, carrier terms and measurement window across groups. If volume only supports two groups, test A against B first, then B against C. A before-and-after comparison alone is vulnerable to seasonal changes. Test model assistance separately on the same unseen emails.

| Proposed gate | Count it this way |
| --- | --- |
| Link earns its cost | Compare staffed contacts per 100 scheduled pickups for B versus A and include additional messaging and carrier costs. Keep the link if it pays for itself, shoppers need less help and collection performance holds up. |
| Reply handling reduces staffed contacts by 25% | Compare C versus B. Count every staffed missed-pickup contact per 100 scheduled pickups, including repeat contacts. Track distinct shoppers who needed help and their follow-ups separately. |
| At least 50% recovered without staff in under 24 hours | Start at the earlier of the first shopper report or verified carrier failure. Fix eligibility rules before routing and include later handoffs and unresolved eligible cases after a full 24 hours of follow-up. Also report the rate across all missed-pickup tickets, including those still awaiting evidence. Success needs an agreed visit, carrier confirmation and a delivered notice. |
| At least 95% of promised updates on time | Delivered by the promised time divided by all updates due. A missing delivery is late. |
| Physical pickup holds up | Compare the share of all confirmed misses with a collection scan received within seven days of the first verified miss. Include staff-owned cases. Also report the narrower rate after a rebooking. |
| Zero duplicate bookings or unauthorised charges | Pause automatic booking on the first occurrence. Test twice the observed peak and inspect overdue promises and the oldest open case. |

## Run it locally

To see the replay, extract the ZIP and open `review/Pickup_Operations.html` in a browser. To try your own messages, use Python 3.9 or newer. Open a terminal in the extracted project folder and install the time-zone data first.

**Windows (PowerShell)**

```powershell
py -3 -m pip install -r requirements.txt
py -3 agent/demo.py P101 --reply "Which one is earlier?"
py -3 -m unittest discover -s agent
```

**macOS or Linux**

```sh
python3 -m pip install -r requirements.txt
python3 agent/demo.py P101 --reply "Which one is earlier?"
python3 -m unittest discover -s agent
```

The [implementation guide](agent/README.md) covers the carrier contract, the simulated clock and the scope of the tests.

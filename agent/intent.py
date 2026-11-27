"""Task-limited local intent recognition. Curated examples, no network or keys."""
import math
import re
from collections import Counter

from messages import SPANISH, plain_spanish


EXAMPLES = {
    "pickup": [
        "The courier never came to collect my return",
        "My return pickup failed can I book another collection",
        "I waited at home all afternoon and nobody came",
        "My pickup window ended is the driver still coming",
        "The collection was missed my parcel is still here",
        "Will the courier be able to find my pickup address",
        "Could you help reschedule my collection",
        "The courier missed my pickup",
        "Pickup failed",
        "My parcel was never collected",
        "The courier never took the box",
        "The driver didn't show up",
    ],
    "other": [
        "Where is my refund my money has not reached my bank",
        "Where is my returned parcel on the way to the warehouse",
        "Can I exchange the shoes for a different size",
        "My order never arrived",
        "My delivery hasn't arrived",
    ],
}
WORDS = re.compile(r"[a-z]+")
STOP = set("a an the all my you has is at can i to for be in it of am me how and was are on help please".split())
FINANCIAL = re.compile(r"\b(compensat\w*|reimburs\w*|refund|waiv\w*|voucher|store credit|"
                       r"pay me|charged|money back|double charge)\b", re.I)
PICKUP_PRICING = re.compile(r"\b(?:fees?|costs?|how much|who (?:pays|covers)|(?:pay|paid) for|"
                            r"(?:a|any|another|extra|additional) charge|charge (?:me|my card)|"
                            r"(?:have|need) to pay|(?:is|will) [^?!.]{0,32}\bfree)\b", re.I)
CONDITIONAL_FEE = re.compile(
    r"\b(?:if|assuming|provided|as long as)\b[^.!?;]{0,40}\b(?:no (?:charge|fee)|free of charge)\b", re.I)
REFUND_STATUS = re.compile(
    r"\b(?:where(?:'s| is) (?:my |the )?refund|when (?:will|can|should) (?:i|we) "
    r"(?:get|receive|expect) (?:my |our |the |a )?refund|refund (?:status|hasn.t arrived|not received))\b", re.I)
PARCEL = r"(?:it|(?:the|my|our) (?:parcel|return|package|box))"
COURIER = r"(?:driver|courier)"
DROP_POINT = r"(?:drop[- ]?off(?: point)?|parcel (?:shop|locker)|post office|depot|locker|pickup point)"
DROP_POINT_ES = r"(?:punto de (?:entrega|recogida|devolucion)|(?:oficina de )?correos|taquilla)"
SHOP_STAFF = r"(?:shop assistant|(?:shop |store |counter )?clerk|shopkeeper)"
HANDOVER_ES = (r"(?:se (?:lo|la|los|las) (?:di|dimos|entregue|entregamos)|"
               r"(?:di|dimos|entregue|entregamos) (?:el paquete|la caja)) "
               r"(?:al |a la |a un |a una )(?:dependient[ea]|encargad[oa]|emplead[oa]|"
               r"mensajer[oa]|repartidor(?:a)?)")
COMPLETED_COLLECTION = (
    r"(?:was|got|has been) (?:already |finally )?(?:collected|picked up|dropped off)",
    rf"(?:dropped|handed) {PARCEL} (?:off|in) (?:at|to) "
    rf"(?:the |a |my )?{DROP_POINT}",
    rf"(?:already|finally) (?:collected|picked (?:{PARCEL} )?up)",
    rf"{COURIER} (?:did come|came|stopped by) and (?:collect(?:ed)? {PARCEL}|pick(?:ed)? {PARCEL} up)",
    rf"{COURIER} (?:came and |has |had )?(?:just |already |finally )?"
    rf"(?:(?:collected|picked up|took|has taken) {PARCEL}|picked {PARCEL} up)",
    rf"(?:someone|somebody|they) (?:else |already |just )?(?:collected {PARCEL}|picked {PARCEL} up)",
    rf"{COURIER} (?:now |already )?has {PARCEL}",
    rf"and (?:now |already )?(?:has|took|collected|picked up) {PARCEL}",
    rf"and (?:just |finally )?picked {PARCEL} up",
    rf"(?:he|she|they) (?:just |already )?(?:took|collected|picked up) {PARCEL}",
    rf"(?:handed|gave) {PARCEL} (?:in|over)",
    rf"(?:i|we)(?:'ve| have)? (?:already )?(?:posted|mailed|returned) {PARCEL}",
    rf"(?:i|we)(?:'ve| have)? (?:already )?(?:taken|took|brought|dropped off|left|handed in) {PARCEL} "
    rf"(?:at|to|with) (?:the |a |my )?(?:{DROP_POINT}|{SHOP_STAFF})",
    rf"{PARCEL}(?: is|'s) (?:already |now )?(?:at|in) (?:the |a |my )?{DROP_POINT}",
    rf"(?:i|we) (?:already )?dropped {PARCEL} off",
    rf"(?:handed|gave) {PARCEL} (?:over )?to (?:the|your|a) (?:{COURIER}|{SHOP_STAFF})",
    rf"(?:handed|gave) (?:him|her|them) {PARCEL}",
)
ALREADY_COLLECTED = re.compile(r"\b(?:" + "|".join(COMPLETED_COLLECTION) + r")\b", re.I)
COLLECTION_QUESTION = re.compile(
    rf"\b(?:did (?:the |my )?{COURIER} (?:collect|pick)|was {PARCEL} (?:collected|picked up)|"
    rf"(?:has|have) (?:the |my )?{COURIER} (?:collected|picked))\b", re.I)
DOUBTS_COLLECTION = re.compile(
    r"\b(?:don't think|do not think|not sure|can't confirm|cannot confirm|doubt|if|whether|"
    r"is it possible|no se si|no estoy segur[oa]|y si)\b[^.!?;]{0,48}$", re.I)
NEGATED_HANDOVER = re.compile(r"\b(?:not|never|nobody|no one|no|nunca|tampoco) (?:already |actually |really )?$", re.I)
VISIT = r"(?:pickups?|collections?|drivers?|couriers?|visits?)"
DECLINED_VISIT = (
    r"(?:no longer want|do not want|don't want) to return (?:it|this|the item)",
    r"(?:nothing (?:left )?to (?:return|collect|pick ?up)|no longer have (?:anything to return|it|"
    r"(?:the|my) (?:parcel|package|box|item)))",
    r"cancel (?:my |the |this )?(?:pickup|collection|return|courier|driver)",
    r"(?:never|didn't|did not) (?:ask for|request(?:ed)?|book(?:ed)?) (?:a |the |this )?(?:pickup|collection)",
    r"(?:do not|don't|don't want to|do not want to|stop) (?:schedule|arrange|book|rebook|reschedule)",
    r"(?:don't (?:want|need)|do not (?:want|need)|no need for|no longer (?:need|want)) "
    rf"(?:another |a new |a second |a |the |this |any more )?{VISIT}",
    rf"(?:no (?:more|further)|no repeat) {VISIT}",
    r"(?:do not|don't|no need to) send (?:anyone|somebody|someone) (?:again|else)",
    rf"(?:do not|don't) send (?:a |the |another |second |new )*{COURIER}",
    r"(?:(?:i(?:'ll| will| can| would rather|'d rather) |let me )drop|dropping|dropped) "
    r"(?:it|the parcel|my return) off myself",
)
NO_REBOOK = re.compile(r"\b(?:" + "|".join(DECLINED_VISIT) + r")\b", re.I)
HUMAN_REQUEST = re.compile(
    r"\b(?:speak|talk|chat|connect|transfer|put me through)(?: me)? (?:with |to )?"
    r"(?:(?:a|an|your|the|real|live|human|customer|support|service) )*"
    r"(?:human|person|agent|representative|operator|advisor|support)\b|"
    r"\b(?:want|need|get me|ask for|let me speak to) (?:a |an |to talk to |to speak to |real |live |human |support )*"
    r"(?:person|human|agent|representative|operator)\b|"
    r"\b(?:someone|somebody|a person|a representative|an agent|your team)"
    r"(?: (?:from|on|in) (?:your |the )?(?:support )?team)? (?:please )?"
    r"(?:call|ring|contact|phone|email|message) me\b", re.I,
)
CANCEL_REQUEST = re.compile(
    r"\b(?:i (?:want|need|would like) to cancel|i'd like to cancel|(?:please|can you|could you) cancel)\b|"
    r"\b(?:call off|scrap) (?:[^.!?;]{0,35} )?(?:pickup|collection|visit|booking|appointment)\b|"
    r"\b(?:keeping (?:the|my|this) (?:item|order|purchase)|changed my mind about returning)\b|"
    r"\b(?:pickup|collection|courier) (?:is |is now )?no longer (?:needed|required|wanted)\b|"
    r"^(?:please )?cancel(?: (?:it|this|that|the booking|the appointment))?[.! ]*$", re.I,
)
COURIER_ON_WAY = re.compile(
    r"\b(?:courier|driver)(?:'s| is| was|(?: just)? (?:said|says|told me|called|texted|messaged))\s+"
    r"[^.!?]{0,60}?\b(?:on (?:my|his|her|their|the) way|heading (?:here|over|to (?:me|my address))|"
    r"still coming|will (?:still )?(?:come|arrive|be here)|running late|outside|at (?:my|the) door|"
    r"(?:\d+|a few|five|ten|fifteen|twenty|thirty) (?:min(?:ute)?s?|hours?) (?:away|out))\b", re.I,
)
ADDRESS_CHANGE = re.compile(
    r"\b(?:wrong|incorrect|different|old|outdated|new|incomplete) (?:pickup |collection |street )?address\b|"
    r"\b(?:address|postcode|zip code|flat number|apartment number)\b[^;.!?]{0,36}\b"
    r"(?:wrong|incorrect|outdated|missing|incomplete|has changed|isn't mine|is not mine)\b|"
    r"\b(?:change|correct|fix|amend|update|switch) (?:my |the |our |that |this )?(?:pickup |collection )?"
    r"(?:address|location)\b|"
    r"\b(?:different|new|another) (?:pickup |collection )(?:location|place)\b|"
    r"\b(?:collect|pickup|pick) (?:it|(?:the|my|our) (?:package|parcel|return|box)) (?:up )?from "
    r"(?:(?:a different|another|a new) (?:location|place|address)|[^.!?;]{1,42}\binstead)\b|"
    r"\b(?:i(?:'ve| have)?|we(?:'ve| have)?) (?:just |recently )?(?:moved|changed (?:my|our) address)\b", re.I,
)
NEGATED_CANCEL = re.compile(r"\b(?:don't|do not|never) (?:want (?:you )?to )?(?:cancel|call off)\b", re.I)
DECLINED_COMPENSATION = re.compile(
    r"\b(?:no (?:compensation|reimbursement) (?:is )?(?:needed|necessary|requested)|"
    r"(?:don't|do not) (?:want|need) (?:any )?(?:compensation|reimbursement))\b", re.I,
)
DATED_NO_SHOW = re.compile(
    r"\bno (?:courier|driver) (?:on |again )?(today|yesterday|this morning|this afternoon|last night|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I)
MISSED = (r"(?:missed|failed|never (?:came|arrived|showed up|turned up)|"
          r"(?:nobody|no one) (?:came|showed up|turned up|has shown up|has come)|"
          r"(?:did not|didn['’]?t|has not|hasn['’]?t) (?:come|show(?:ed|n)? up|turn(?:ed)? up|arriv(?:e|ed)))")
MULTIPLE = r"(?:both|two|three|four|five|several|multiple|[2-9]|[1-9]\d+)"
REPEAT_VISIT = r"(?:second|third|fourth|fifth|[2-9](?:nd|rd|th)|[1-9]\d+(?:st|nd|rd|th))"
VISIT_NOUN = r"(?:pickups?|collections?|visits?|appointments?|attempts?)"
VISIT_DAY = r"(?:yesterday|today|monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
REPEAT_COUNT = (
    rf"{MISSED} (?:on )?{VISIT_DAY} (?:or|and) (?:on )?{VISIT_DAY}",
    rf"{MISSED} (?:on )?(?:either|both) (?:days?|times?|occasions?|visits?|attempts?)",
    rf"(?:both|each) (?:times|days|occasions) (?:i|we) (?:waited|stayed) "
    rf"[^.!?]{{0,40}}?{MISSED}",
    rf"{MISSED}\b[^.!?;]{{0,45}}?\b(?:twice|again|{MULTIPLE} times|{REPEAT_VISIT} (?:pickup|collection|attempt))",
    rf"{MISSED}\b[^.!?;]{{0,45}}[.!?;]\s*(?:this|that|it)(?: is| was|'s) the {REPEAT_VISIT} time",
    rf"(?:pickup|collection|pick up)\b[^.!?;]{{0,35}}\btwice\s+and\s+{MISSED}",
    rf"(?:{REPEAT_VISIT} time|again)[, ]+[^.!?;]{{0,45}}?\b{MISSED}",
    rf"(?:{MULTIPLE}|{REPEAT_VISIT}|another) (?:courier |driver |pickup |collection )?no[- ]shows?",
    rf"no[- ]show (?:twice|again)|missed (?:{MULTIPLE}|(?:both|all) (?:of )?(?:the|my|our)) {VISIT_NOUN}",
    rf"(?:{MULTIPLE}|{REPEAT_VISIT}) (?:failed|missed) {VISIT_NOUN}",
    rf"{MULTIPLE} (?:pickup |collection )?{VISIT_NOUN} (?:have |were )?(?:failed|missed)",
    rf"(?:{REPEAT_VISIT}|another) (?:pickup|collection) (?:has |was )?(?:failed|missed)",
    rf"(?:{MULTIPLE} days? (?:in a row|running)|(?:stayed|waited) (?:at )?home twice)"
    rf"[^.!?;]{{0,55}}?{MISSED}",
    rf"{MISSED}[^.!?;]{{0,50}}?\b{MULTIPLE} days? (?:in a row|running)",
    rf"(?:two|both|2) {VISIT_NOUN}\b[^.?!;]{{0,40}}?\b{MISSED} (?:for|to) (?:either|both)",
    rf"(?:(?:that|this|it)(?:'s| is| was) )?(?:twice now|the second time)[,.:!?;\s]+"
    rf"(?:the |my |our )?(?:courier |driver |pickup |collection )?(?:has |was )?{MISSED}",
)
REPEAT = re.compile(r"\b(?:" + "|".join(REPEAT_COUNT) + r")\b", re.I)
PICKUP_CONTEXT = re.compile(
    r"\b(pickup|pick up|courier|driver|collect\w*|nobody came|no one came|waited at home)\b", re.I)


QUALIFIED_MISS = re.compile(
    rf"\b{MISSED}\b|\b(?:never|not|wasn't|hasn't been|weren't) (?:collected|picked up|taken)\b|"
    r"\b(?:rebook|reschedule|another pickup|another collection|new pickup|still coming|still here|"
    r"window (?:has )?ended|find my pickup address|nobody (?:came|turned up)|never took)\b", re.I)
PARTIAL_COLLECTION = re.compile(
    r"\b(?:(?:collected|picked up|took) (?:only |just )?(?:one|some) of (?:them|the (?:parcels|packages|boxes))|"
    r"(?:only|just) (?:picked up|took|collected) one (?:parcel|package|box|return)|"
    r"(?:picked up|took|collected) (?:only |just )?(?:the first|one) (?:parcel|package|box|return) "
    r"(?:but|and) (?:left|the other|the second)|"
    r"(?:handed|gave) (?:the (?:courier|driver) )?the (?:first|second) (?:one|parcel|box|package)|"
    r"(?:entregue|di) (?:al (?:mensajero|repartidor) )?el (?:primer|segundo) (?:paquete|bulto)|"
    r"(?:vino (?:por|a (?:recoger|buscar))|se llevo|recogio|retiro) (?:solo |solamente )?"
    r"un[oa] de (?:l[oa]s|mis|nuestr[oa]s) (?:(?:dos|tres|cuatro|\d+) )?(?:cajas|paquetes|bultos)|"
    r"(?:solo|solamente) (?:se llevo|recogio) un[oa])\b", re.I)

SPANISH_INTENTS = (
    ("human", r"\b(?:agente|persona|hablar con|llamadme)\b"),
    ("money", r"\b(?:cobrar|cobraron|coste|cargo|compensacion|pagar|dinero)\b"),
    ("refund_status", r"\breembolso\b"),
    ("cancel", r"\b(?:cancelar|cancela|no quiero (?:otra|la) recogida|"
               r"no (?:quiero|necesito) (?:devolver(?:lo|la)?|que (?:lo |la )?recojan)|"
               r"me (?:lo|la) quedo|no hace falta que vengan)\b"),
    ("address_change", r"\b(?:direccion|domicilio|otro lugar)\b"),
    ("repeat_miss", r"\b(?:dos veces|otra vez|segunda vez|tercera vez|dos dias (?:seguidos|consecutivos)|"
                    r"(?:ni )?ayer (?:ni|y) hoy|(?:ni )?hoy (?:ni|y) ayer|"
                    r"ninguna de las dos (?:citas|visitas|recogidas)|"
                    r"(?:en )?las dos ocasiones[^.!?]{0,45}(?:nadie vino|no vino))\b"),
    ("courier_en_route", r"\b(?:esta en camino|esta en la puerta)\b"),

    ("already_collected", rf"\b(?:{HANDOVER_ES}|(?:lo |la )?(?:entregue|deje) (?:el paquete |la caja )?"
                          r"(?:al (?:mensajero|repartidor)|en (?:un|el) (?:punto|locker|buzon)|en correos)|"
                          rf"(?:lo |la )?(?:lleve|entregue|deje) (?:el paquete |la caja )?"
                          rf"(?:al |a |en (?:un |el |la )?){DROP_POINT_ES}|"
                          rf"(?:el paquete|la caja) (?:ya )?esta en (?:un |el |la )?{DROP_POINT_ES}|"
                          r"(?:se (?:lo|la) (?:han llevado|llevaron)|ya (?:lo|la) han recogido)|"
                          r"ya (?:se )?(?:lo )?(?:recogieron|recogio|llevo)|"
                          r"(?:mensajero|repartidor) (?:se lo llevo|recogio el paquete))\b"),
    ("pickup", r"\b(?:nadie (?:vino|ha venido)|no (?:ha |han )?"
               r"(?:venido|llegado|vino|vinieron|llego|recogieron|lo recogio|lo han recogido))\b"),
)
FRUSTRATED = re.compile(
    r"\b(?:ridiculous|frustrat(?:ed|ing)|furious|took (?:a|the) day off|lost a day of work)\b", re.I)


CLAUSE_BREAK = re.compile(r"[.!?;,\n]+|\b(?:but|however|except|although|since then|afterwards|"
                          r"and|because|since|after|as|when|so|pero|aunque|porque|asi que|sin embargo|"
                          r"desde entonces|despues|al final|y)\b")
REPORTED_MISS = re.compile(
    rf"\b(?:{MISSED}|never collected|(?:wasn't|was not|not) collected|nadie (?:vino|ha venido)|"
    r"no (?:vino|llego|ha venido|lo recogieron)|recogida (?:fallida|fallo))\b")
PARCEL_STILL_HERE = re.compile(
    r"(?:i|we) still have (?:it|(?:the|my|our) (?:parcel|package|box|return))|"
    r"(?:it|(?:the|my|our) (?:parcel|package|packaging|box|return))(?: is|'s) still (?:here|with me|with us)|"
    r"(?:i|we) (?:never|haven't|have not) handed (?:it|the parcel|the package) over|"
    r"(?:aun|todavia|sigo) (?:tengo|teniendo) (?:el paquete|la caja)|"
    r"(?:el paquete|la caja) (?:sigue|esta) (?:aqui|conmigo)")
CUSTODY_DETAIL = re.compile(
    r"\b(?:parcel|package|box|bag|label|locker|post office|driver has|courier has|"
    r"it(?:'s| is) (?:already |now )?(?:with|at|in)|handed|shipped|dropped|"
    r"paquete|bulto|caja|taquilla|correos|envie|entregue|lleve|deje)\b")
STILL_WITH_SHOPPER = re.compile(
    rf"(?:{PARCEL}(?: is not| isn't|'s not) (?:at|in) (?:the |a )?{DROP_POINT}|"
    rf"(?:i|we) (?:haven't|have not|didn't|did not|never) (?:take|taken|bring|brought|leave|left) {PARCEL}"
    rf" (?:to|at|in|with) (?:the |a )?(?:{DROP_POINT}|{SHOP_STAFF})|"
    rf"(?:yo )?(?:no|nunca|tampoco) {HANDOVER_ES}|"
    rf"(?:el paquete|la caja) no esta en (?:un |el |la )?{DROP_POINT_ES}|"
    rf"(?:yo )?no (?:lo |la )?(?:lleve|entregue|deje) (?:el paquete |la caja )?"
    rf"(?:al |a |en (?:un |el |la )?){DROP_POINT_ES})"
    r"(?: yet| now| todavia| aun)?")
PICKUP_FOLLOWUP = re.compile(
    r"(?:can|could|would) (?:you|i|we) (?:please )?(?:"
    r"(?:book|arrange|schedule|get|request) (?:a new|a replacement|another) (?:pickup|collection|visit)|"
    r"(?:rebook|reschedule)(?: (?:it|(?:the|my) (?:pickup|collection)))?|"
    r"check(?: (?:it|the (?:times|available times|pickup)|for me))?)|"
    r"(?:please )?(?:rebook|reschedule)(?: (?:it|(?:the|my) (?:pickup|collection)))?|"
    r"(?:i|we) (?:don't|do not) want to miss another (?:pickup|collection)|"
    r"what (?:should|can) (?:i|we) do(?: now| next)?|what (?:happens|now)(?: next)?|"
    r"(?:is|was) (?:the )?(?:courier|driver) still coming|"
    r"(?:puedes|podemos|puedo) (?:concertar|reservar|programar) (?:otra|una nueva) recogida|"
    r"(?:gracias|thanks|thank you|please|por favor)")


def sentiment_only(text):
    if not FRUSTRATED.search(text):
        return False
    rest = FRUSTRATED.sub("", text.casefold())
    return bool(re.fullmatch(r"(?:[\s,.!]|this is|i'm|i am|i |for this|work|off)*", rest))


def unverified_update(text):
    parts = [part.strip(" :¿¡-") for part in CLAUSE_BREAK.split(plain_spanish(text))]
    reports = [bool(REPORTED_MISS.search(part)) for part in parts]
    if not any(reports):
        return False
    first_miss = reports.index(True)
    for index, part in enumerate(parts):
        if not part or reports[index]:
            continue
        if PARCEL_STILL_HERE.fullmatch(part) or STILL_WITH_SHOPPER.fullmatch(part):
            continue
        if PICKUP_FOLLOWUP.fullmatch(part) or sentiment_only(part):
            continue
        if index > first_miss or CUSTODY_DETAIL.search(part):
            return True
    return False


def spanish_intent(text):
    text = plain_spanish(text)
    text = re.sub(r"\b(?:no (?:quiero |hay que )?cancelar|no canceles|no quiero quedarmelo)\b", "", text)
    if re.search(r"\b(?:no se si|no estoy segur[oa]|puedes (?:comprobar|ver) si)\b", text):
        return "unknown"
    visit_text = re.sub(
        r"\b(?:(?:llame|escribi|pregunte|comprobe|introduje la direccion) (?:dos|tres) veces|"
        r"(?:segunda|tercera) vez que (?:(?:te|les|os) )?(?:escribo|llamo|pregunto))\b", "", text)
    for label, pattern in SPANISH_INTENTS:
        source = visit_text if label == "repeat_miss" else text
        for event in re.finditer(pattern, source):
            if label == "already_collected" and re.search(r"\b(?:no|nunca|tampoco)\s*$", text[:event.start()]):
                continue
            return label
    return None


CUSTODY_REPORT = re.compile(
    r"\b(?:parcel|package|box|return|it)(?: is|'s| was) (?:(?:already|now|still) )?(?:with|at|in)\b|"
    r"\b(?:they|someone|carrier|courier|driver|shop|office|store|clerk) (?:already |now |still )?"
    r"(?:has|have|took|accepted) (?:it|the|my|our|this)\b|"
    r"\b(?:took|brought|returned|taking|bringing) (?:it|this|that|the parcel|my return) "
    r"(?:back|to|into)\b|\ben manos (?:de|del)\b")
CHANGED_VISIT = re.compile(
    r"\b(?:address|postcode|(?:wrong|different|old|new) (?:building|entrance|flat|location)|"
    r"fee|charge|refund|cancel|hold off|stop|wait a minute|no collection needed|changed my mind|"
    r"(?:do not|don't) (?:send|come)|no (?:one|courier|driver) needs? to come|"
    r"direccion|cobro|cancelar|adresse|adreca|annul\w*|anul\w*|frais|tarif|depos\w*|"
    r"deixat|lliurat|entregat|remis|remise|relais|ramass\w*|recollit|canviat|demena\w*|"
    r"handed|dropped|shipped|collected|picked up|recogid[oa]s? ya|never happened|plans (?:have )?changed|"
    r"can.t be (?:home|there)|won.t be (?:home|there)|(?:something|what) (?:else |just |has )*"
    r"(?:happened|changed)|second label)\b")


def booking_concern(message):
    text = plain_spanish(message).replace("\u2019", "'")
    return bool(CUSTODY_REPORT.search(text) or CHANGED_VISIT.search(text))


def explicit_intent(text):
    text = re.sub(r"\bpick[- ]up\b", "pickup", text, flags=re.I).replace("\u2019", "'")
    partial = PARTIAL_COLLECTION.search(plain_spanish(text))
    if partial:
        prefix = text[:partial.start()]
        if DOUBTS_COLLECTION.search(prefix):
            return "unknown"
        if not NEGATED_HANDOVER.search(prefix):
            return "partial_collection"
    spanish = spanish_intent(text) if SPANISH.search(text) else None
    if spanish not in {None, "pickup"}:
        return spanish
    if HUMAN_REQUEST.search(text):
        return "human"
    cancel_text = NEGATED_CANCEL.sub("", text)
    if NO_REBOOK.search(cancel_text) or CANCEL_REQUEST.search(cancel_text):
        return "cancel"
    if ADDRESS_CHANGE.search(text):
        return "address_change"
    if COLLECTION_QUESTION.search(text):
        return "unknown"
    for collection in ALREADY_COLLECTED.finditer(text):
        prefix = text[:collection.start()]
        if DOUBTS_COLLECTION.search(prefix):
            return "unknown"
        if not NEGATED_HANDOVER.search(prefix):
            return "already_collected"
    if COURIER_ON_WAY.search(text):
        return "courier_en_route"
    if REFUND_STATUS.search(text) and not PICKUP_PRICING.search(text):
        return "refund_status"
    money_text = DECLINED_COMPENSATION.sub("", text)
    pickup_fee = PICKUP_CONTEXT.search(text) and PICKUP_PRICING.search(money_text)
    if FINANCIAL.search(money_text) or CONDITIONAL_FEE.search(money_text) or pickup_fee:
        return "money"
    if REPEAT.search(text) or len(set(DATED_NO_SHOW.findall(text.casefold()))) > 1:
        return "repeat_miss"
    if unverified_update(text):
        return "visit_update"
    if FRUSTRATED.search(text):
        return "complaint" if sentiment_only(text) or QUALIFIED_MISS.search(text) else "unknown"
    return spanish


def features(text):
    text = re.sub(r"\bpick[- ]up\b", "pickup", text.lower())
    return Counter(word for word in WORDS.findall(text) if word not in STOP)


def similarity(a, b):
    dot = sum(count * b[token] for token, count in a.items())
    norm = math.sqrt(sum(n * n for n in a.values()) * sum(n * n for n in b.values()))
    return dot / norm if norm else 0.0


PROTOTYPES = [(label, features(text)) for label, texts in EXAMPLES.items() for text in texts]


def read_intent(text):
    """Nearest-example classifier; its heuristic threshold is not calibrated confidence."""
    explicit = explicit_intent(text)
    if explicit:
        return explicit
    words = features(text)
    if not words:
        return "unknown"
    scores = {label: 0.0 for label in EXAMPLES}
    for label, prototype in PROTOTYPES:
        scores[label] = max(scores[label], similarity(words, prototype))
    best, second = sorted(scores, key=scores.get, reverse=True)[:2]
    if scores[best] < 0.24 or scores[best] - scores[second] < 0.06:
        return "unknown"
    if best == "pickup" and not (PICKUP_CONTEXT.search(text.replace("-", "")) and QUALIFIED_MISS.search(text)):
        return "unknown"
    return best

"""Read a shopper's reply against the windows actually shown on their return."""
import re
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache

from messages import plain_spanish, window_label

WEEKDAY = r"(?:mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)"
DAY = re.compile(rf"\b{WEEKDAY}\b")
QUESTION_MARK = re.compile(r"[?¿？]")
TRANSLATIONS = {
    "lunes": "monday", "martes": "tuesday", "miercoles": "wednesday", "jueves": "thursday",
    "viernes": "friday", "sabado": "saturday", "domingo": "sunday", "opcion": "option", "gracias": "thanks",
    "tues": "tue", "weds": "wed", "thur": "thu", "thurs": "thu",
    "thx": "thanks", "perfecto": "perfect", "vale": "okay", "pls": "please", "plz": "please",
}
COURTESY = re.compile(r"^(?:(?:thank you|thanks|yes|yep|sure|fine|great|perfect|ok(?:ay)?) )+")
THANKS = re.compile(
    r"(?:thanks|thank you)(?: (?:very much|so much|a lot|a ton|for sorting that(?: out)?|for your help|"
    r"por (?:la|tu|su) ayuda))?|"
    r"cheers(?: mate)?|that helps|all sorted(?: now)?|todo claro|mil thanks|"
    r"ok(?:ay)?|got it|understood|entendido|great|perfect|see you then|nos vemos entonces")
SEE_YOU = re.compile(rf"(?:(?:great|perfect|thanks|thank you|ok(?:ay)?) )?see you (?:on )?({WEEKDAY})")
SCHEDULE = r"(?:pickup|collection|appointment|booking)"
DETAILS = re.compile(
    rf"(?:what(?:'s| is) (?:my|the) (?:booking|pickup|collection|confirmation) (?:reference|number|code)|"
    rf"(?:what (?:time|day)|when) (?:is|was) (?:my|the) {SCHEDULE}(?: (?:scheduled|booked)(?: for)?)?|"
    rf"is (?:my|the) (?:(?:{WEEKDAY}) )?{SCHEDULE} (?:still )?(?:booked|confirmed)|"
    r"(?:a que hora|cuando) (?:es|esta (?:prevista|programada|confirmada)) (?:mi|la) recogida|"
    r"(?:cual es|me recuerdas) (?:mi|la|el) (?:numero de reserva|referencia(?: de (?:mi|la) reserva)?)|"
    r"esta confirmada (?:mi|la) (?:reserva|recogida))(?: again| please)?")
BOOKING_FIELD = re.compile(r"\b(?:time|day|date|window|reference|number|code|slot|appointment|booking|visit|"
                          r"pickup|collection|recogida|hora|referencia|codigo|reserva|fecha|franja)\b")
READ_QUESTION = re.compile(r"^(?:what|when|which|is|could you (?:remind|tell)|can you (?:remind|tell)|"
                           r"me puedes (?:recordar|decir)|puedes (?:recordarme|decirme)|cuando|a que hora|cual)\b")
SECOND_REQUEST = re.compile(r"\b(?:but|if|instead|actually|unless|also|and|or|except|missed|never|wasn.t|"
                            r"didn.t|not|no|why|change|move|reschedule|cancel|new|different|other|fee|charge|"
                            r"pero|aunque|ademas|cambiar|mover|cancelar|otra|otro|sino|y|si)\b")
OFFER_QUESTION = re.compile(r"^(?:what|which|how|when|is|are|can|could|would|does|"
                            r"cuando|como|que|cual|puedo|podemos|esta disponible)\b")
EARLIEST = re.compile(r"\b(?:earlier|earliest|soonest|comes first|starts first|happens first|primero|mas temprano)\b")
DECLINE = re.compile(r"(?:(?:the |el )?(" + WEEKDAY + r") (?:doesn't work|does not work|"
                     r"isn't good|is no good|no me (?:va|viene) bien)(?: for me)?|"
                     r"(?:i can.t (?:do|make)|no puedo el) (" + WEEKDAY + r"))")
EITHER = re.compile(r"(?:(?:either )?" + WEEKDAY + r" or " + WEEKDAY + r" (?:is (?:fine|good)|works)(?: for me)?|"
                    r"i can do either " + WEEKDAY + r" or " + WEEKDAY + r")")
SHOPPING_FEEDBACK = re.compile(r"(?:but )?(?:(?:this|that)(?: is|'s) the last time i "
                               r"(?:order|shop|buy) (?:from|with) you|i(?:'ll| will) never "
                               r"(?:order|shop|buy) (?:from|with) you again)[.! ]*", re.I)
AMENDMENT = re.compile(r"\b(?:move|reschedule|switch|change|instead|later time|different (?:day|time)|"
                       r"can.t (?:make|do|be home)|won.t be (?:home|there)|doesn.t work|not available|"
                       r"cambiar|reprogramar|no puedo|no me va bien)\b")
WEEKDAYS = tuple("monday tuesday wednesday thursday friday saturday sunday".split())
PREFIX = re.compile(r"^(?:(?:please )?book(?: me)?(?: for)?|(?:please )?reserve|(?:please )?reserva(?:me)?(?: para)?|"
                    r"please|on|i(?:'d like| would like| want)(?: to (?:choose|go with|take))?|"
                    r"i (?:prefer|choose|can do)|i(?:'ll| will) take|me (?:va|viene) bien|prefiero|elijo) ")
SUFFIX = re.compile(r"(?: works(?: for me)?| is (?:fine|good)| sounds good| (?:is|would be) perfect(?: for me)?|"
                    r" me (?:va|viene) bien)?(?: please| thanks| thank you)?$")
ORDINALS = ("first", "second", "third", "fourth", "fifth")
CHANGE = re.compile(r"\b(?:move|reschedule|switch|change|actually|instead|"
                    r"cambia(?:r|lo|la|rlo|rla)?|mover(?:lo|la)?|pasar(?:lo|la)?|reprogramar|trasladar)\b")


def plain(message):
    text = message.casefold().replace("\u2019", "'")
    text = re.sub(r"\bsí\b", "yes", text)
    text = plain_spanish(text).replace("muchas gracias", "gracias")
    words = re.sub(r"[,!.¡?¿？！]", " ", text).split()
    normalized = " ".join(normalize_word(word) for word in words)
    return (normalized.replace("por favor", "please").replace("nos vemos el ", "see you ")
            .replace(" por la tarde", " afternoon").replace(" por la manana", " morning"))


def preference(text):
    text = PREFIX.sub("", COURTESY.sub("", text))
    return re.sub(r"^(?:the|el|la) ", "", SUFFIX.sub("", text))


def is_acknowledgement(case, message):
    if QUESTION_MARK.search(message):
        return False
    text = plain(message)
    parts = re.split(r"[,!.¡？！]+", message)
    if text and all(THANKS.fullmatch(plain(part)) for part in parts if part.strip()):
        return True
    if THANKS.fullmatch(text):
        return True
    meeting = SEE_YOU.fullmatch(text)
    if not case.accepted_start:
        return False
    booked = datetime.fromisoformat(case.accepted_start)
    if meeting:
        return meeting[1][:3] == booked.strftime("%a").casefold()
    slot = case.accepted_slot.casefold()
    return preference(text) in {slot, "slot " + slot, "option " + slot, booked.strftime("%A").casefold(),
                                booked.strftime("%a").casefold()}


def asks_booking_details(message):
    return bool(DETAILS.fullmatch(plain(message)))


def can_read_booking(message):
    text = plain(message)
    return (bool(QUESTION_MARK.search(message)) and bool(READ_QUESTION.search(text))
            and bool(BOOKING_FIELD.search(text)) and not SECOND_REQUEST.search(text)
            and len(text.split()) <= 16 and not re.search(r"[.,;!?]\s*\S", message.strip().strip("!?. ")))


def change_after_booking(message, start):
    text = plain(message)
    weekday = datetime.fromisoformat(start).strftime("%a").casefold() if start else None
    return bool(AMENDMENT.search(text)) or any(day[:3] != weekday for day in DAY.findall(text))


def requested_day(message):
    text = plain(message)
    days = DAY.findall(text)
    if not CHANGE.search(text) or re.search(r"\b(?:don't|do not) (?:move|change|switch)|"
                                            r"\bno (?:quiero |(?:lo |la )?)?(?:cambi|mover|pasar)", text):
        return None
    if len(days) == 1:
        return days[0].capitalize()
    alternative = re.search(rf"\b({WEEKDAY}) instead\b", text)
    if alternative:
        return alternative[1].capitalize()
    destination = re.findall(rf"\b(?:to|al|para el) ({WEEKDAY})\b", text)
    return destination[0].capitalize() if len(destination) == 1 else None


@dataclass(frozen=True)
class Reply:
    discusses_offer: bool = False
    slot: str = None
    revision: int = None
    answer: str = ""
    windows: tuple = ()


def one_edit(a, b):
    shorter, longer = sorted((a, b), key=len)
    if len(longer) - len(shorter) > 1:
        return False
    i = next((i for i, (x, y) in enumerate(zip(shorter, longer)) if x != y), len(shorter))
    if len(shorter) < len(longer):
        return shorter[i:] == longer[i+1:]
    return (shorter[i+1:] == longer[i+1:] or
            (shorter[i:i+2] == longer[i:i+2][::-1] and shorter[i+2:] == longer[i+2:]))


@lru_cache(maxsize=512)
def normalize_word(word):
    if word in TRANSLATIONS or word == "thank" or len(word) < 5 or not word.isalpha():
        return TRANSLATIONS.get(word, word)
    matches = [term for term in (*WEEKDAYS, "thanks", "gracias") if one_edit(word, term)]
    if len(matches) == 1:
        return TRANSLATIONS.get(matches[0], matches[0])
    return word


def read_choice(case, message):
    if not case.offered:
        return Reply()
    text = plain(message)
    parts = re.split(r"[.!;]\s+|,\s+(?=but )", message, flags=re.I)
    if len(parts) == 2 and SHOPPING_FEEDBACK.fullmatch(parts[1].strip()):
        text = plain(parts[0])
    selected = preference(text)
    question = bool(QUESTION_MARK.search(message) or OFFER_QUESTION.search(text))
    named = set(day[:3] for day in DAY.findall(text))
    mentioned = tuple(slot for slot, start in case.offered_starts.items()
                      if start.strftime("%a").casefold() in named)
    if question and (named or EARLIEST.search(text) or re.search(r"\b(?:option|slot|window|times)s?\b", text)):
        if EARLIEST.search(text):
            earliest = min(case.offered_starts, key=case.offered_starts.get)
            return Reply(True, answer="earliest", windows=(earliest,))
        return Reply(True, answer="times", windows=mentioned)
    if DECLINE.fullmatch(text):
        return Reply(True, answer="alternatives", windows=tuple(slot for slot in case.offered if slot not in mentioned))
    if EITHER.fullmatch(text) and len(named) == 2 and mentioned:
        available_days = {case.offered_starts[slot].date() for slot in mentioned}
        if len(available_days) == len(mentioned):
            return Reply(True, min(mentioned, key=case.offered_starts.get), answer="either", windows=mentioned)
    tagged = re.fullmatch(r"(?:option |slot )?([a-z0-9]+)/(\d{1,8})", selected)
    if tagged:
        if question:
            return Reply(True)
        return Reply(True, tagged[1].upper(), int(tagged[2]))

    matches = []
    for slot, start in case.offered_starts.items():
        start = start.astimezone(case.offered_ends[slot].tzinfo)
        part = "morning" if start.hour < 12 else "afternoon"
        if start.hour >= 16:
            part = "evening"
        days = (start.strftime("%a").casefold(), start.strftime("%A").casefold())
        names = {slot.casefold(), f"slot {slot}".casefold(), f"option {slot}".casefold(), *days}
        names.update(f"{day} {part}" for day in days)
        window = case.offered[slot]
        names.update(plain(label) for label in (window, window_label(window, "es")))
        long_window = f"{start:%A %d %B}, {start:%H:%M}–{case.offered_ends[slot]:%H:%M %Z}"
        names.add(plain(long_window))
        day = start.day
        suffix = "th" if 10 < day % 100 < 14 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
        names.add(f"{day}{suffix}")
        index = (case.offer_order or tuple(case.offered)).index(slot)
        if index < len(ORDINALS):
            names.update(ORDINALS[index] + tail for tail in ("", " one", " option", " slot", " window"))
        if selected in names:
            matches.append(slot)
    if len(matches) == 1 and not question:
        return Reply(True, matches[0])
    return Reply(bool(matches))


def discussing_offered_time(case, message, selected_slot):
    reply = read_choice(case, message)
    return reply.discusses_offer and (selected_slot is None or reply.slot == selected_slot)

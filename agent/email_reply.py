import re


QUOTE_HEADER = re.compile(r"(?:on .+ wrote:|el .+ escribi[oó]:)", re.I)
PHONE_FOOTER = re.compile(r"(?:sent from my|enviado desde mi) (?:iphone|ipad|android)\b[.!]?", re.I)
SIGN_OFF = re.compile(
    r"(?:best(?: regards)?|kind regards|regards|cheers|thanks|thank you|un saludo|saludos|gracias)"
    r"\b[,!]?\s*(?P<name>.*)", re.I)
NAME = re.compile(r"[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ]+(?:[ '-][A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ]+){0,2}")
REQUEST_WORDS = re.compile(
    r"\b(?:no|not|wait|hold|stop|cancel|cancelled|change|move|changed|wrong|address|fee|charge|paid|"
    r"delay|late|already|collected|pickup|courier|never|actually|instead|cancelar|espera|recogido|direccion|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I)


def current_reply(message, previous=""):
    lines = [line.strip() for line in message.splitlines() if line.strip()]
    active = []
    for index, line in enumerate(lines):
        if QUOTE_HEADER.fullmatch(line):
            tail = lines[index + 1:]
            if tail and previous and " ".join(tail).split() == previous.split():
                break
            if tail and tail[0].startswith(">"):
                continue
        if not line.startswith(">"):
            active.append(line)
    if active and PHONE_FOOTER.fullmatch(active[-1]):
        active.pop()
    if len(active) > 1:
        for index in (len(active) - 2, len(active) - 1):
            closing = SIGN_OFF.fullmatch(active[index])
            if not closing:
                continue
            name = " ".join([closing["name"], *active[index + 1:]]).strip()
            if not name or (NAME.fullmatch(name) and not REQUEST_WORDS.search(name)):
                if index or not name:
                    active = active[:index]
                elif active[0].casefold().startswith(("thanks", "thank you", "gracias")):
                    return active[0][:closing.start("name")].strip(" ,!")
                break
    return "\n".join(active)

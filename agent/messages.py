"""Shopper messages for the pickup pilot."""
import re
import unicodedata


def plain_spanish(text):
    return "".join(c for c in unicodedata.normalize("NFD", text.lower())
                   if not unicodedata.combining(c))


SPANISH = re.compile(r"\b(?:mensajero|repartidor|recogida|recoger|paquete|jueves|miércoles|miercoles|"
                     r"lunes|martes|viernes|sábado|sabado|domingo|opción|gracias|sí|perfecto|vinieron|vin[oí]|"
                     r"devolución|recogieron|reembolso|cobrar|dirección|entregué|dejé|llevó|"
                     r"ha venido|días seguidos|dependient[ea]|encargad[oa]|se (?:lo|la) di|"
                     r"devolverlo|devolverla|me lo quedo|me la quedo|hace falta que vengan|lo recojan|"
                     r"segunda vez|tercera vez|nadie|punto de entrega|correos|reserva(?:da)?|referencia|"
                     r"qu[eé] hora|por (?:tu|la) ayuda)\b", re.I)
DAYS = {"Mon": "lun", "Tue": "mar", "Wed": "mié", "Thu": "jue", "Fri": "vie", "Sat": "sáb", "Sun": "dom"}
MONTHS = dict(zip("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(),
                  "ene feb mar abr may jun jul ago sep oct nov dic".split()))


def window_label(window, language):
    if language != "es":
        return window
    words = re.split(r"(\W+)", window)
    return "".join(DAYS.get(word, MONTHS.get(word, word)) for word in words)


def offer_message(case, changed, show_again, complaint):
    spanish = case.language == "es"
    windows = [f"{slot}: {window_label(window, case.language)}" for slot, window in case.offered.items()]
    choices = (" o " if spanish else " or ").join(windows)
    if case.offer_number > 1:
        codes = (" o " if spanish else " or ").join(f"{slot}/{case.offer_number}" for slot in case.offered)
        instructions = (f"{choices}. Responde {codes} o pulsa el botón de la nueva opción."
                        if spanish else f"{choices}. Reply {codes}, or select a button on the updated offer.")
    else:
        instructions = (f"Responde con el día o la opción que prefieras. {choices}." if spanish else
                        f"Reply with the day or option you want, or select its button. {choices}.")
    if changed:
        return ("Han cambiado los horarios. " if spanish else "The pickup times have changed. ") + instructions
    if show_again:
        return instructions
    if spanish:
        return ("Siento la espera. El transportista ha registrado la recogida fallida. "
                "Puedo reservar otra sin coste. " + instructions)
    opening = "I'm sorry you had to wait."
    if complaint:
        opening = ("I'm sorry you lost a day of work." if re.search(r"(?:day off|day of work)", complaint, re.I)
                   else "I'm sorry this has been frustrating.")
    return (opening + " The carrier recorded the missed pickup. I can arrange a free replacement. "
            "Which time works for you? " + instructions)


def confirmed(case, booking):
    window = window_label(booking["window"], case.language)
    if case.language == "es":
        return f"Tu nueva recogida está confirmada para {window}. Referencia {booking['reference']}."
    return f"Your new pickup is confirmed for {window}. Reference {booking['reference']}."


def checking_carrier(case, inquiry, cutoff):
    if case.language == "es":
        return ("La franja de recogida ya ha terminado. "
                f"He pedido al transportista que compruebe la visita ({inquiry}). "
                f"Te escribiremos antes de las {cutoff:%H:%M %Z}, aunque todavía estemos esperando su respuesta.")
    return ("Your scheduled pickup window has ended. I can't confirm a later visit. "
            f"I've asked the carrier to check ({inquiry}). We'll update you here by {cutoff:%H:%M %Z}, "
            "even if we're still waiting.")


MESSAGES = {
    "Unverified booking": (
        "I couldn't verify the booking against the time you chose.",
        "No he podido comprobar que la reserva coincida con el horario que elegiste. Soporte lo "
        "revisará.",
    ),
    "Address flagged": (
        "The carrier flagged an address detail. Support will check the existing booking with you before "
        "confirming the visit.",
        "El transportista ha señalado un problema con la dirección. Soporte revisará contigo la reserva "
        "antes de confirmar la visita.",
    ),
    "Visit status changed": (
        "The latest carrier record needs checking before we can confirm the visit.",
        "Soporte tiene que comprobar el estado de la visita antes de confirmarla.",
    ),
    "Window already started": (
        "The booked window has already started and we can't verify you received confirmation.",
        "La franja de recogida ya ha empezado y no podemos verificar que hayas recibido la confirmación. "
        "Soporte comprobará la visita.",
    ),
    "Confirmation undelivered": (
        "We couldn't deliver confirmation of the booked pickup.",
        "No hemos podido entregarte la confirmación. Soporte comprobará la reserva y te contactará por "
        "otra vía.",
    ),
    "Carrier silent": (
        "We still haven't heard back from the carrier. Support will check the visit and update you here.",
        "Seguimos sin respuesta del transportista sobre tu recogida. Soporte comprobará la visita y te "
        "escribirá.",
    ),
    "No available windows": (
        "There are no available standard slots to offer.",
        "No quedan franjas disponibles. Soporte preguntará al transportista por otras opciones.",
    ),
    "Incomplete carrier record": (
        "I couldn't verify the carrier's pickup details. Support will check before arranging a visit.",
        "No he podido verificar los datos de la recogida. Soporte consultará con el transportista.",
    ),
    "Pickup update undelivered": (
        "The pickup update did not reach the shopper.",
        "No hemos podido entregar el aviso de la recogida. Soporte intentará contactarte por otra vía.",
    ),
    "Offer undelivered": (
        "The replacement options did not reach the shopper.",
        "Las nuevas opciones de recogida no se han podido entregar. Soporte intentará contactarte.",
    ),
    "New carrier evidence": (
        "New carrier evidence needs review after the replacement booking.",
        "El transportista ha actualizado los datos de la visita. Soporte comprobará qué ha cambiado en "
        "la reserva.",
    ),
    "Change confirmed booking": (
        "I've asked Support to check {day} with the carrier. Your current booking for {window} stays in "
        "place until you hear back.",
        "He pedido a soporte que consulte si se puede cambiar al {day}. Tu reserva para {window} sigue "
        "en pie hasta que te confirmen un cambio.",
    ),
    "Follow-up after booking": (
        "You contacted us again after confirmation. The team will review the existing booking.",
        "Soporte revisará tu mensaje y la reserva existente antes de modificar la recogida.",
    ),
    "Change pending booking": (
        "The visit for {window} may still go ahead. Support is checking your request with the carrier. "
        "Please wait for an update.",
        "La visita para {window} podría seguir en pie. Soporte está consultando tu solicitud con el "
        "transportista. Te avisarán por aquí.",
    ),
    "Person requested": (
        "I've passed your pickup question to our support team. A person will take it from here.",
        "He pasado tu consulta a soporte. Una persona se pondrá en contacto contigo.",
    ),
    "Pickup declined": (
        "I'll leave the pickup as it is. Support can help with cancellation or another way to return it.",
        "No he reservado otra recogida. Soporte comprobará contigo si hay que cancelar una visita "
        "existente o cambiar el método de devolución.",
    ),
    "Refund status": (
        "The returns team can check where your refund stands.",
        "El equipo de devoluciones comprobará el estado de tu reembolso.",
    ),
    "New pickup details": (
        "Support will check your latest update before arranging another visit.",
        "Soporte comprobará lo que nos has contado antes de programar otra visita.",
    ),
    "Partial collection": (
        "Support will check which parcel was collected before arranging another visit.",
        "Soporte comprobará qué paquete se ha recogido antes de programar otra visita.",
    ),
    "Shopper reports collection": (
        "Thanks for letting us know you handed over the parcel. Support will check the carrier scan.",
        "Gracias por avisarnos de que entregaste el paquete. Soporte comprobará el escaneo con el transportista.",
    ),
    "Missing shopper details": (
        "We still need more detail to understand your request.",
        "Soporte te escribirá para aclarar qué pasó con tu recogida antes de cambiarla.",
    ),
    "Shopper reports address change": (
        "I've paused rebooking. Support will check the pickup address with you before offering new "
        "times.",
        "He detenido la nueva reserva. Soporte verificará contigo la dirección antes de ofrecerte otro "
        "horario.",
    ),
    "Courier on the way": (
        "You mentioned the courier may still be coming. Support will check before arranging another "
        "pickup.",
        "El mensajero podría seguir de camino. Soporte comprobará la visita antes de programar otra.",
    ),
    "Merchant exception": (
        "A merchant-specific exception needs approval.",
        "La tienda tiene que aprobar una excepción. Te avisaremos cuando tengamos su respuesta.",
    ),
    "Compensation requested": (
        "I've sent your request for compensation to the merchant team for review. They'll get back to you here.",
        "He enviado tu solicitud de compensación a la tienda para que la revise. Te responderán por aquí.",
    ),
    "Payment question": (
        "I've passed your payment question to the merchant team for review. They'll get back to you "
        "here.",
        "He enviado tu consulta sobre el cobro a la tienda. Te responderán por aquí.",
    ),
    "Repeated carrier misses": (
        "The carrier recorded {count} missed attempts. A person will review the visit history.",
        "El transportista ha registrado {count} intentos fallidos. Una persona revisará el historial de "
        "visitas.",
    ),
    "Repeated shopper misses": (
        "I'm sorry you've had to wait more than once. Support will check the visits with the carrier and "
        "update you here.",
        "Siento que hayas tenido que esperar varias veces. Soporte comprobará las visitas con el transportista y "
        "te escribirá por aquí.",
    ),
    "Shopper marked unavailable": (
        "The carrier marked you as unavailable. Support will check the visit details with the carrier.",
        "El transportista indica que no estabas disponible. Soporte revisará contigo y con el "
        "transportista los detalles de la visita.",
    ),
    "Carrier reports collection": (
        "The carrier reports that the parcel was collected.",
        "El transportista indica que ha recogido tu paquete. Soporte comprobará el escaneo antes de "
        "programar otra visita.",
    ),
    "Unknown carrier status": (
        "The carrier supplied an unfamiliar status. The team will verify it.",
        "Soporte comprobará con el transportista el estado de tu recogida.",
    ),
    "Booking not verified": (
        "The carrier has not verified the earlier booking attempt.",
        "El transportista aún no ha verificado la reserva anterior. Soporte la comprobará antes de crear "
        "otra.",
    ),
    "Address not verified": (
        "The address detail still needs verification. Support will follow up with you.",
        "Queda por verificar un dato de la dirección. Soporte se pondrá en contacto contigo.",
    ),
    "Unknown number of misses": (
        "We can't verify whether this was the first missed pickup.",
        "No hemos podido verificar cuántos intentos de recogida se han realizado. Soporte lo comprobará.",
    ),
    "Repeat pickup funding": (
        "We need the merchant to check who covers this repeat pickup.",
        "La tienda tiene que confirmar quién cubrirá el coste de la nueva recogida. Te avisaremos antes "
        "de reservarla.",
    ),
    "Offer ended": (
        "Those pickup options have expired. Reply here or reopen the link to see current times.",
        "Esas franjas de recogida han caducado. Responde aquí o vuelve a abrir el enlace para ver los horarios.",
    ),
    "Offer withdrawn": (
        "I've withdrawn the earlier pickup options. Support will check your latest message before "
        "arranging a visit.",
        "He retirado las opciones de recogida anteriores. Soporte revisará tu mensaje antes de programar "
        "una visita.",
    ),
    "Permission changed": (
        "The merchant's authorization changed before booking.",
        "La autorización de la tienda ha cambiado. Soporte verificará las condiciones antes de hacer una "
        "nueva reserva.",
    ),
    "Carrier timeout": (
        "The carrier hasn't confirmed the visit for {window}. It may still go ahead. Support is checking "
        "the original request and will update you here.",
        "El transportista aún no ha confirmado la visita para {window}. Podría seguir en pie. Soporte "
        "comprobará la solicitud original y te avisará por aquí.",
    ),
    "Notice pending": (
        "The carrier has confirmed the pickup. We're still trying to deliver the confirmation.",
        "El transportista ha confirmado la recogida. Seguimos intentando entregar el aviso.",
    ),
    "Collection on record": (
        "The carrier has reported collecting your parcel. The collection scan is on your return.",
        "El transportista ha confirmado que ha recogido tu paquete.",
    ),
    "No collection scan": (
        "Your replacement was booked for {window}. I don't have a collection scan for it yet.",
        "Tu recogida estaba reservada para {window}. Todavía no hay un escaneo de recogida.",
    ),
    "Thanks": (
        "You're welcome.",
        "¡Gracias!",
    ),
    "Clarify booking": (
        "Could you say what you need? If you're asking for a change, tell us what should change.",
        "¿Qué necesitas? Si quieres cambiar la recogida, dinos qué hay que cambiar.",
    ),
    "Clarify pickup": (
        "Is this about a courier collecting a return from you? What happened during the pickup window?",
        "¿Qué pasó con la recogida de tu devolución?",
    ),
    "Address needed": (
        "The carrier needs one address detail: {field}. Please check it in the return portal.",
        "El transportista necesita que completes este dato en el portal de devoluciones: {field}.",
    ),
    "Original window": (
        "The scheduled pickup window ends {end:%a %d %b at %H:%M %Z}. I can't confirm when the courier "
        "will arrive.",
        "La franja de recogida termina el {end:%d/%m a las %H:%M %Z}. Todavía no tengo una hora de "
        "llegada confirmada.",
    ),
    "Awaiting carrier reply": (
        "The carrier hasn't acknowledged the new booking yet. I'll check the original request.",
        "El transportista aún no ha confirmado la reserva. Voy a comprobar la solicitud original.",
    ),
    "Review collection": (
        "The carrier now reports that your parcel was collected. The team has this update and will check "
        "it against your return.",
        "El transportista nos indica que ya ha recogido tu paquete. Soporte comprobará el escaneo con "
        "los datos de tu devolución.",
    ),
    "Review status unavailable": (
        "I couldn't verify a fresh carrier status. The team still has your case and will check the "
        "pickup.",
        "No he podido verificar una actualización del transportista. Soporte sigue revisando tu "
        "recogida.",
    ),
    "Review updated": (
        "The team has the latest carrier information and will check it alongside your report.",
        "Soporte ha recibido los últimos datos del transportista y los comparará con lo que nos has "
        "contado.",
    ),
    "Amendment under review": (
        "The visit for {window} may still go ahead. I've asked Support to check {day} with the carrier "
        "and send you an update.",
        "La visita para {window} podría seguir en pie. He pedido a soporte que consulte con el "
        "transportista si puede cambiarse al {day}. Te avisarán por aquí.",
    ),
}


WEEKDAYS_ES = dict(zip("Monday Tuesday Wednesday Thursday Friday Saturday Sunday".split(),
                       "lunes martes miércoles jueves viernes sábado domingo".split()))
ADDRESS_FIELDS_ES = {"flat number": "número de piso", "building entrance": "entrada del edificio",
                     "apartment or entrance detail": "piso o entrada del edificio"}


def shopper_message(case, reason, **details):
    english, spanish = MESSAGES[reason]
    if case.language != "es":
        return english.format(**details)
    if "window" in details:
        details["window"] = window_label(details["window"], "es")
    if "day" in details:
        day = details["day"][:3].lower()
        details["day"] = next(value for name, value in WEEKDAYS_ES.items() if name[:3].lower() == day)
    if "field" in details:
        details["field"] = ADDRESS_FIELDS_ES.get(details["field"], "datos de la dirección de recogida")
    return spanish.format(**details)


def reply_language(text):
    text = plain_spanish(text)
    if re.search(r"\b(?:bonjour|merci|jeudi|mercredi|livreur|coursier|colis|adresse|demain|je (?:ne|peux|suis)|mon paquet)\b", text):
        return "fr"
    if re.search(r"\b(?:dijous|dimecres|missatger|recollida|bon dia|gracies|adreca|no puc|el (?:meu )?paquet)\b", text):
        return "ca"
    return None


LANGUAGE_OPTIONS = {
    "fr": set("bonjour merci oui non pour moi je peux ne pas prendre le la les un une des de du l c est ce que "
              "convient possible va bien me ou et quelle heure quel horaire quand au matin apres midi soir "
              "s il vous plait parfait ok d accord mercredi jeudi demain plus tot premier creneau".split()),
    "ca": set("hola bon dia gracies si no puc el la les un una de per a em va be o i quina hora quin horari "
              "quan mati tarda vespre es podria pot ser possible perfecte dijous dimecres dema mes aviat "
              "primer recollida franja sisplau si us plau".split()),
}


def simple_foreign_reply(text, language):
    words = re.findall(r"[a-z]+", plain_spanish(text))
    return bool(words) and all(word in LANGUAGE_OPTIONS[language] for word in words)


def language_help(language, review, has_offer):
    if language == "fr":
        if review:
            return "L’équipe d’assistance va vérifier votre demande et vous répondra ici."
        link = " Pour choisir un créneau, le lien de votre e-mail reste disponible." if has_offer else ""
        return "Pourriez-vous préciser votre demande en anglais ou en espagnol ?" + link
    if review:
        return "L’equip de suport revisarà la teva petició i et respondrà aquí."
    link = " Per triar una franja, pots fer servir l’enllaç del correu." if has_offer else ""
    return "Pots explicar què necessites en anglès o en castellà?" + link


def answer_offer(case, choice):
    spanish = case.language == "es"
    labels = [window_label(case.offered[slot], case.language) for slot in choice.windows if slot in case.offered]
    options = " / ".join(labels)
    if choice.answer == "earliest" and labels:
        return ("La primera franja es " if spanish else "The earliest window is ") + options + "."
    if choice.answer == "alternatives":
        if labels:
            return ("También puedes elegir " if spanish else "You can choose this instead: ") + options + "."
        return ("¿Necesitas otro horario?" if spanish else "Do you need another time?")
    if choice.answer == "times" and labels:
        return ("El horario disponible es " if spanish else "The available time is ") + options + "."
    return ("¿Qué franja prefieres? También puedes usar el enlace del correo." if spanish else
            "Which window would you like? You can still use the link in your email.")

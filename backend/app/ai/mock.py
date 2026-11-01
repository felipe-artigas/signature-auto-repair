"""Modo de pruebas del asistente.

Simula las decisiones de un modelo con reglas simples para ejercitar el circuito completo (herramientas,
validaciones, confirmación y persistencia) sin consumir la API de OpenAI. No interpreta lenguaje natural como lo
haría un modelo real: extrae datos con patrones y sigue un guion fijo. La interfaz lo identifica como modo de pruebas.
"""

import json
import re
from datetime import datetime
from typing import Any

from app.ai.providers import FunctionCall, ProviderResult, TurnContext, function_call_item

BRANDS = [
    "Mercedes-Benz", "Mercedes Benz", "Mercedes", "Range Rover", "Land Rover", "Aston Martin", "Rolls-Royce",
    "Alfa Romeo", "Porsche", "BMW", "Audi", "Ferrari", "Lamborghini", "Maserati", "Bentley", "McLaren",
    "Jaguar", "Lexus", "Volvo", "Mini", "Tesla", "Volkswagen", "Toyota", "Ford", "Chevrolet", "Jeep",
]
_BRAND_CANONICAL = {"mercedes benz": "Mercedes-Benz", "mercedes": "Mercedes-Benz"}
_MODEL_STOP = {
    "y", "que", "con", "del", "de", "hace", "año", "modelo", "tiene", "es", "el", "la", "me", "se", "un", "una",
    "anda", "hay", "cuando", "pero", "desde", "en", "a", "por", "km", "kilómetros", "kilometros",
}

SERVICE_KEYWORDS = [
    ("sistemas-de-frenos", r"fren|pastilla|disco"),
    ("suspension-y-direccion", r"suspensi|amortigu|direcci|calles irregulares|pozo|bache|tren delantero"),
    ("transmision", r"caja|cambio|transmisi|embrague|tironea"),
    ("climatizacion", r"aire acondicionado|climatiz|calefacci"),
    ("electricidad-y-electronica", r"bater|eléctric|electric|electr[oó]nic|luz de|tablero|sensor"),
    ("mantenimiento-preventivo", r"service|mantenimiento|cambio de aceite|filtro"),
    ("diagnostico-computarizado", r"diagn[oó]stic|scanner|esc[aá]ner|check engine|testigo"),
    ("inspeccion-general", r"inspecci|revisi[oó]n general|pre ?compra|viaje"),
]
SYMPTOM_PATTERN = re.compile(
    r"ruido|vibra|falla|golpe|pierde|p[eé]rdida|humo|no arranca|tironea|calienta|temperatura|chirr|"
    r"luz|testigo|olor|traba|consume|tiembla|zumbido|ruidos|problema|se apaga|aceite",
    re.I,
)

QUESTIONS: dict[str, str] = {
    "vehicle": "Para comenzar, ¿podría indicarme la marca, el modelo y el año de su vehículo?",
    "year": "Gracias. ¿De qué año es el vehículo?",
    "problem_description": "¿Qué servicio necesita o qué está notando en el vehículo?",
    "mileage_km": "Entiendo. ¿Cuántos kilómetros tiene aproximadamente el vehículo?",
    "onset": "¿Desde cuándo nota esta situación?",
    "frequency": "¿El síntoma aparece de manera constante o intermitente?",
    "full_name": "Para registrar la solicitud, ¿me indica su nombre y apellido?",
    "phone": "¿A qué número de teléfono podemos contactarlo?",
    "email": "¿Y cuál es su correo electrónico?",
    "preferred_contact": "¿Prefiere que lo contactemos por teléfono, WhatsApp o correo electrónico?",
    "availability": "¿Qué días y franjas horarias le resultan convenientes para acercar el vehículo?",
}


def _text_of(item: dict[str, Any]) -> str:
    content = item.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(part.get("text", "") for part in content if isinstance(part, dict))
    return ""


def extract_fields(message: str, expecting: str | None) -> dict[str, Any]:
    text = message.strip()
    low = text.lower()
    found: dict[str, Any] = {}

    if m := re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text):
        found["email"] = m.group(0)
    for brand in BRANDS:
        if m := re.search(rf"\b{re.escape(brand)}\b", text, re.I):
            found["make"] = _BRAND_CANONICAL.get(brand.lower(), brand)
            tokens = re.findall(r"[\w\-.]+", text[m.end():])
            model = []
            for token in tokens:
                token = token.strip(".,-")
                if not token or token.lower() in _MODEL_STOP or re.fullmatch(r"(19|20)\d\d", token) or len(model) >= 3:
                    break
                model.append(token)
            if model:
                found["model"] = " ".join(model)
            break
    if m := re.search(r"\b(19[5-9]\d|20[0-3]\d)\b", text):
        found["year"] = int(m.group(1))
    if m := re.search(r"(\d{1,3}(?:[.,]\d{3})+|\d+)\s*(?:mil\s*)?(?:km|kms|kil[oó]metros)", low):
        value = int(re.sub(r"\D", "", m.group(1)))
        found["mileage_km"] = value * 1000 if re.search(r"\d\s*mil", m.group(0)) else value
    phone_match = re.search(r"\+?\d[\d\s\-()]{7,}\d", text)
    if phone_match and len(re.sub(r"\D", "", phone_match.group(0))) >= 8 and "km" not in low[phone_match.end():phone_match.end() + 4]:
        found["phone"] = phone_match.group(0).strip()
    if m := re.search(r"(?:me llamo|mi nombre es|soy)\s+([A-Za-zÁÉÍÓÚÑáéíóúñ]+(?:\s+[A-Za-zÁÉÍÓÚÑáéíóúñ]+){0,3})", text, re.I):
        found["full_name"] = m.group(1).title()
    if re.search(r"whats?app", low):
        found["preferred_contact"] = "whatsapp"
    elif expecting == "preferred_contact" and re.search(r"mail|correo", low):
        found["preferred_contact"] = "email"
    elif expecting == "preferred_contact" and re.search(r"llam|tel[eé]fono", low):
        found["preferred_contact"] = "telefono"
    if re.search(r"intermitente|a veces|de vez en cuando|no siempre", low):
        found["frequency"] = "intermitente"
    elif re.search(r"constante|siempre|todo el tiempo", low):
        found["frequency"] = "constante"
    if m := re.search(r"(hace\s+\w+\s+(?:d[ií]as?|semanas?|mes(?:es)?|a[nñ]os?)|desde\s+[\w\s]{3,30})", low):
        found["onset"] = m.group(1)
    for slug, pattern in SERVICE_KEYWORDS:
        if re.search(pattern, low):
            found["service_slug"] = slug
            break
    if SYMPTOM_PATTERN.search(low) and len(text) > 15:
        found["problem_description"] = text[:600]

    # Respuesta directa a la última pregunta.
    if expecting and expecting not in found and expecting != "vehicle":
        if expecting in ("full_name", "onset", "availability", "problem_description"):
            if not re.fullmatch(r"(no s[eé]|prefiero no|paso|ninguna?)\.?", low):
                found[expecting] = text[:300]
        elif expecting == "mileage_km" and (digits := re.sub(r"\D", "", text)):
            found["mileage_km"] = int(digits) * (1000 if re.search(r"\bmil\b", low) else 1)
        elif expecting == "year" and re.fullmatch(r"\d{4}", text):
            found["year"] = int(text)
        elif expecting == "frequency" and re.search(r"no s[eé]", low):
            found["frequency"] = "no_sabe"
    if expecting == "availability" and "availability" not in found and re.search(
        r"lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|ma[nñ]ana|tarde|semana", low
    ):
        found["availability"] = text[:300]
    return found


class MockProvider:
    name = "mock"

    def respond(self, instructions, items, tools, ctx: TurnContext) -> ProviderResult:
        start = max(
            (i for i, it in enumerate(items) if it.get("role") == "user" or _text_of(it).startswith("EVENTO")),
            default=0,
        )
        trigger = items[start] if items else {}
        names = {it["call_id"]: it["name"] for it in items[start:] if it.get("type") == "function_call"}
        outputs = {
            names.get(it["call_id"]): json.loads(it["output"])
            for it in items[start:]
            if it.get("type") == "function_call_output"
        }
        previous_assistant = [_text_of(it) for it in items[:start] if it.get("role") == "assistant"]
        last_assistant = previous_assistant[-1] if previous_assistant else ""
        asked = {field for field, q in QUESTIONS.items() if any(q in t for t in previous_assistant)}

        if _text_of(trigger).startswith("EVENTO: confirmado"):
            return self._registration_flow(outputs)

        message = _text_of(trigger)
        if ctx.status == "registrada":
            return self._post_registration(message, outputs, ctx)

        expecting = next((f for f, q in QUESTIONS.items() if q in last_assistant), None)
        if "update_intake" not in outputs:
            fields = extract_fields(message, expecting)
            if fields:
                args = {k: fields.get(k) for k in tools_fields(tools, "update_intake")}
                return self._call("update_intake", args)
        if "request_confirmation" in outputs:
            result = outputs["request_confirmation"]
            if result.get("ok"):
                return self._say(
                    "Preparé un resumen con los datos de su consulta. Por favor, revíselo y presione Confirmar "
                    "para registrar la solicitud. Si algo no es correcto, indíqueme qué desea modificar."
                )

        update = outputs.get("update_intake")
        if update and update.get("errors"):
            first_error = next(iter(update["errors"].values()))
            return self._say(f"{first_error} ¿Podría indicarlo nuevamente?")

        intake = {**ctx.intake}
        if ctx.status == "esperando_confirmacion" and not update:
            return self._say(
                "Su resumen está listo para confirmar con el botón Confirmar. Si desea modificar algún dato, "
                "indíquemelo y lo actualizo."
            )
        next_field = self._next_question(intake, asked)
        if next_field:
            question = QUESTIONS[next_field]
            thanked = question.startswith(("Gracias", "Entiendo", "Para comenzar"))
            prefix = "Gracias. " if update and update.get("saved_fields") and not thanked else ""
            return self._say(prefix + question)
        return self._call("request_confirmation", {})

    @staticmethod
    def _next_question(intake: dict[str, Any], asked: set[str]) -> str | None:
        if not intake.get("make") or not intake.get("model"):
            return "vehicle"
        if not intake.get("year"):
            return "year"
        if not intake.get("problem_description") and not intake.get("service_slug"):
            return "problem_description"
        order = ["mileage_km"]
        if intake.get("problem_description"):
            order += ["onset", "frequency"]
        order += ["full_name", "phone", "email", "preferred_contact", "availability"]
        required = {"full_name", "phone", "email"}
        for field in order:
            if not intake.get(field) and (field in required or field not in asked):
                return field
        return None

    def _registration_flow(self, outputs: dict[str, Any]) -> ProviderResult:
        for step in ("find_customer", "create_customer", "create_vehicle"):
            if step not in outputs:
                return self._call(step, {})
            if not outputs[step].get("ok"):
                return self._say("No pude completar el registro en este momento. Por favor, intente nuevamente.")
        if "create_service_request" not in outputs:
            return self._call("create_service_request", {"staff_summary": ""})
        result = outputs["create_service_request"]
        if not result.get("ok"):
            return self._say("No pude registrar la solicitud. Por favor, intente nuevamente en unos minutos.")
        return self._say(
            f"Su solicitud quedó registrada con el código {result['request_code']}. Nuestro equipo la revisará y "
            "se comunicará con usted. ¿Desea que consulte horarios disponibles para acercar el vehículo?"
        )

    def _post_registration(self, message: str, outputs: dict[str, Any], ctx: TurnContext) -> ProviderResult:
        low = message.lower()
        if "create_appointment" in outputs:
            result = outputs["create_appointment"]
            if result.get("ok"):
                when = datetime.strptime(result["slot"], "%Y-%m-%dT%H:%M").strftime("%d/%m a las %H:%M")
                return self._say(
                    f"Registré la solicitud de turno para el {when}. Queda pendiente de confirmación por parte del "
                    "taller, que se comunicará con usted para confirmarlo."
                )
            return self._say(f"{result.get('error', 'No fue posible reservar ese horario.')} ¿Desea elegir otro?")
        if "check_availability" in outputs:
            slots = outputs["check_availability"].get("slots", [])
            if not slots:
                return self._say(
                    "En este momento no hay horarios libres en los próximos días. El taller se comunicará con usted "
                    "para coordinar una fecha."
                )
            listed = "; ".join(
                f"{i}) {datetime.strptime(s, '%Y-%m-%dT%H:%M').strftime('%d/%m %H:%M')}" for i, s in enumerate(slots[:6], 1)
            )
            return self._say(f"Estos son los horarios disponibles: {listed}. Indíqueme el número de la opción que prefiera.")
        if ctx.offered_slots and (m := re.fullmatch(r"\D*([1-6])\D*", low.strip())):
            index = int(m.group(1)) - 1
            if index < len(ctx.offered_slots):
                return self._call("create_appointment", {"slot_start": ctx.offered_slots[index]})
        if re.search(r"\bs[ií]\b|turno|horario|disponib|cu[aá]ndo", low):
            return self._call("check_availability", {"date_from": None, "days": 7})
        return self._say(
            "Su solicitud ya está registrada y el equipo del taller la revisará. Si desea, puedo consultar horarios "
            "disponibles para acercar el vehículo."
        )

    @staticmethod
    def _say(text: str) -> ProviderResult:
        return ProviderResult(
            output_items=[{"role": "assistant", "content": text}], text=text, function_calls=[]
        )

    @staticmethod
    def _call(name: str, arguments: dict[str, Any]) -> ProviderResult:
        item = function_call_item(name, arguments)
        return ProviderResult(
            output_items=[item],
            text="",
            function_calls=[FunctionCall(item["call_id"], name, item["arguments"])],
        )

    def complete(self, instructions, prompt, max_output_tokens=700, schema=None) -> tuple[str, int, int]:
        raise NotImplementedError("El modo de pruebas usa plantillas para los textos internos.")


def tools_fields(tools: list[dict[str, Any]], name: str) -> list[str]:
    tool = next(t for t in tools if t["name"] == name)
    return list(tool["parameters"]["properties"])

"""Server-side Gemini client: deed extraction and presentation renders.

The API key comes from the backend environment only (Settings.gemini_api_key);
it is never sent to, stored for, or readable by any browser client. Requests
carry only what each task needs -- the uploaded document bytes for extraction,
the sanitized plan image for renders -- never unrelated project data, owner
records, or session information (data minimization).

All network calls go through ``_post_generate``, which tests monkeypatch.
"""

from __future__ import annotations

import base64
import json
import re

import httpx

from saudi_plot_api.config import Settings

_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiUnavailable(Exception):
    """No API key configured on the backend."""


class GeminiError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


_EXTRACTION_PROMPT = """You are a specialized AI that analyzes Saudi real estate deed documents (صك عقاري).

FIRST STEP - VALIDATE THE DOCUMENT:
Determine whether the uploaded document is a Saudi real estate deed (صك عقاري) or a similar official property document (document number, owner names, boundaries الحدود, parcel number, area, Ministry of Justice branding, verification QR codes).

If the document is CLEARLY NOT such a document, return ONLY:
{"is_valid_deed": false, "message": "هذا الملف لا يبدو أنه صك عقاري سعودي. يرجى رفع صك الأرض أو مستند عقاري واضح."}

If it IS, return "is_valid_deed": true and extract ALL visible information:
1. Every owner with name, ID number, ownership percentage.
2. Property details: property id, type, city, district, plan type/number, block, parcel number, area m2.
3. Boundaries (north/south/east/west) with lengths and descriptions.
4. All QR codes; decode content when possible.
5. Document info: number, type, status, Hijri/Gregorian issue dates, previous document, operation type.
6. Any verification URL.
7. Extra fields into extra_information.

CONFIDENCE:
Add a top-level "field_confidence" object with a 0.0-1.0 confidence for each of:
"area_m2", "boundary_north", "boundary_south", "boundary_east", "boundary_west",
"document_number", "city", "district", "parcel_number". Use low values when the
text is unclear or inferred.

OUTPUT: ONLY valid JSON, no markdown fences. null for missing values, numbers as numbers (IDs as strings), Arabic kept as-is.

SCHEMA (when is_valid_deed is true):
{"is_valid_deed": true,
 "document": {"document_number": null, "document_type": null, "document_status": null,
  "issue_date_hijri": null, "issue_date_gregorian": null, "previous_document_number": null,
  "previous_document_date": null, "operation_type": null},
 "owners": [{"name": null, "id_number": null, "ownership_percentage": null}],
 "property": {"property_id": null, "property_type": null, "city": null, "district": null,
  "plan_type": null, "plan_number": null, "block": null, "parcel_number": null, "area_m2": null},
 "boundaries": {"north": null, "south": null, "east": null, "west": null},
 "qr_codes": [{"exists": true, "decoded_text": null, "type": null}],
 "verification": {"verification_url": null},
 "extra_information": {},
 "field_confidence": {}}"""


def _post_generate(settings: Settings, model: str, body: dict) -> dict:
    """Single network entry point (monkeypatched in tests)."""
    url = f"{_API_BASE}/{model}:generateContent"
    try:
        response = httpx.post(
            url,
            params={"key": settings.gemini_api_key},
            json=body,
            timeout=settings.gemini_timeout_seconds,
        )
    except httpx.HTTPError as exc:
        raise GeminiError("provider_unreachable", "The AI provider could not be reached.") from exc
    if response.status_code == 429:
        # Quota exhausted -- distinct code so callers can degrade gracefully
        # instead of surfacing a generic failure to the user.
        raise GeminiError(
            "quota_exceeded",
            "The AI provider quota has been exhausted. Try again later or use manual entry.",
        )
    if response.status_code != 200:
        # Never surface the provider's raw body (it can echo the key context).
        raise GeminiError(
            "provider_error", f"The AI provider rejected the request (HTTP {response.status_code})."
        )
    try:
        return response.json()
    except ValueError as exc:
        # HTTP 200 with a non-JSON body (provider bug or intermediary) must
        # surface as a structured provider error, never an unhandled 500.
        raise GeminiError(
            "provider_bad_format", "The AI provider returned an unexpected format."
        ) from exc


def _require_key(settings: Settings) -> None:
    if not settings.gemini_api_key:
        raise GeminiUnavailable("GEMINI_API_KEY is not configured on the backend")


def _response_parts(payload: dict) -> list[dict]:
    candidates = payload.get("candidates") or []
    if not candidates:
        raise GeminiError("provider_empty_response", "The AI provider returned no result.")
    return (candidates[0].get("content") or {}).get("parts") or []


def extract_deed(settings: Settings, file_bytes: bytes, content_type: str) -> dict:
    """Extract structured deed data. Sends the document only -- nothing else."""
    _require_key(settings)
    body = {
        "contents": [
            {
                "parts": [
                    {"text": _EXTRACTION_PROMPT},
                    {
                        "inlineData": {
                            "mimeType": content_type,
                            "data": base64.b64encode(file_bytes).decode("ascii"),
                        }
                    },
                ]
            }
        ]
    }
    payload = _post_generate(settings, settings.gemini_extraction_model, body)
    text = ""
    for part in _response_parts(payload):
        text += part.get("text") or ""
    result = _parse_json_object(text)
    verdict = result.get("is_valid_deed")
    if verdict is False:
        raise GeminiError(
            "not_a_deed",
            result.get("message") or "The uploaded file does not appear to be a Saudi deed.",
        )
    # Model output is nondeterministic: only an explicit boolean True with the
    # expected container shapes counts as a successful extraction.
    if verdict is not True:
        raise GeminiError("provider_bad_format", "The AI provider returned an unexpected format.")
    for container in ("document", "property", "boundaries", "field_confidence"):
        if container in result and not isinstance(result[container], dict):
            raise GeminiError(
                "provider_bad_format", "The AI provider returned an unexpected format."
            )
    return result


def generate_presentation_render(
    settings: Settings, plan_image: bytes, image_mime: str, style_instructions: str
) -> tuple[bytes, str]:
    """Produce a presentation image from a sanitized plan image.

    Returns (image_bytes, content_type). The input image is the canonical
    engineering SVG/PNG with no owner, deed, or private metadata; the style
    instructions are controlled server-side text.
    """
    _require_key(settings)
    body = {
        "contents": [
            {
                "parts": [
                    {"text": style_instructions},
                    {
                        "inlineData": {
                            "mimeType": image_mime,
                            "data": base64.b64encode(plan_image).decode("ascii"),
                        }
                    },
                ]
            }
        ],
        "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
    }
    payload = _post_generate(settings, settings.gemini_render_model, body)
    for part in _response_parts(payload):
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            mime = inline.get("mimeType") or inline.get("mime_type") or "image/png"
            return base64.b64decode(inline["data"]), mime
    raise GeminiError("provider_no_image", "The AI provider returned no image.")


def _parse_json_object(text: str) -> dict:
    cleaned = text.strip()
    if not cleaned:
        raise GeminiError("provider_empty_response", "The AI provider returned an empty result.")
    # Tolerate accidental markdown fences despite the prompt.
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise GeminiError("provider_bad_format", "The AI provider returned an unexpected format.")
    try:
        result = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise GeminiError(
            "provider_bad_format", "The AI provider returned an unexpected format."
        ) from exc
    if not isinstance(result, dict):
        raise GeminiError("provider_bad_format", "The AI provider returned an unexpected format.")
    return result

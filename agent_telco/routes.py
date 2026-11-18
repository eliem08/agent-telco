"""Carrier webhooks served by agent-telco-web. Twilio calls these; API-key clients do not.

POST /twilio/inbound   Twilio "A message comes in": the text lands in the agent's thread, STOP/START are honoured
POST /twilio/status    Twilio StatusCallback: delivered / undelivered / failed for messages we sent

Every request must carry a valid X-Twilio-Signature: HMAC-SHA1 with TWILIO_AUTH_TOKEN over PUBLIC_URL + path
(+ query) followed by each form field name and value in sorted order, base64-encoded (Twilio's documented
scheme). Without TWILIO_AUTH_TOKEN and an https PUBLIC_URL both routes answer 503 and change nothing.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import sys
from urllib.parse import parse_qs

from .core import TelcoError
from .service import Service, store_lock

STORE_FILE = "agent-telco-telco.json"  # the same file the API's commands use (see _webspec state)
TWIML_EMPTY = b'<?xml version="1.0" encoding="UTF-8"?><Response></Response>'


def twilio_signature(token: str, url: str, params: dict[str, list[str]]) -> str:
    data = url + "".join(k + v for k in sorted(params) for v in sorted(params[k]))
    return base64.b64encode(hmac.new(token.encode(), data.encode("utf-8"), hashlib.sha1).digest()).decode()


def _verified(handler, body: bytes):
    """(params, None) when Twilio signed this request, else (None, (status, ctype, body))."""
    token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    public = os.environ.get("PUBLIC_URL", "").rstrip("/")
    if not token or not public.startswith("https://"):
        msg = b"Twilio webhooks need TWILIO_AUTH_TOKEN and an https PUBLIC_URL"
        return None, (503, "text/plain; charset=utf-8", msg)
    params = parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True)
    expected = twilio_signature(token, public + handler.path, params)
    given = handler.headers.get("X-Twilio-Signature", "")
    if not hmac.compare_digest(expected.encode(), given.encode()):
        return None, (403, "text/plain; charset=utf-8", b"bad or missing X-Twilio-Signature")
    return {k: v[0] for k, v in params.items()}, None


def inbound(handler, body: bytes):
    params, refused = _verified(handler, body)
    if refused:
        return refused
    store = str(handler.data_dir / STORE_FILE)
    try:
        with store_lock(store):
            svc = Service(store)
            # Twilio sends its own STOP/START confirmations and blocks ours, so we only record the opt-out
            r = svc.receive(
                params.get("To", ""),
                params.get("From", ""),
                params.get("Body", ""),
                sid=params.get("MessageSid", ""),
                confirm=False,
            )
            svc.save()
    except TelcoError as e:
        sys.stderr.write(f"twilio inbound refused: {e}\n")  # visible in Twilio's debugger as a 400
        return 400, "text/plain; charset=utf-8", str(e).encode()
    sys.stderr.write(f"twilio inbound: {r['action']} for {r['agent']}\n")
    return 200, "text/xml; charset=utf-8", TWIML_EMPTY


def status(handler, body: bytes):
    params, refused = _verified(handler, body)
    if refused:
        return refused
    store = str(handler.data_dir / STORE_FILE)
    with store_lock(store):
        svc = Service(store)
        found = svc.update_status(
            params.get("MessageSid", ""), params.get("MessageStatus", ""), params.get("ErrorCode", "")
        )
        if found:
            svc.save()
    return 200, "text/xml; charset=utf-8", TWIML_EMPTY  # unknown sids are acknowledged and ignored


ROUTES = {"/twilio/inbound": inbound, "/twilio/status": status}

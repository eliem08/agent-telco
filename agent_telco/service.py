"""The operable exchange: state that survives restarts, and a real carrier when credentials are set.

State lives in one JSON file (numbers, who owns them, opt-outs, threads, rate-limit buckets). The carrier is
Twilio when TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN are set; otherwise messages are recorded but not sent,
and every result says so, so nobody mistakes a dry run for a delivery.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .core import Carrier, Exchange, Message, TelcoError, TokenBucket

E164 = re.compile(r"^\+[1-9]\d{6,14}$")


def check_number(n: str) -> str:
    n = re.sub(r"[\s().-]", "", str(n))
    if not E164.match(n):
        raise TelcoError(f"{n!r} is not an E.164 phone number (like +14155550100)")
    return n


class DryRunCarrier(Carrier):
    """No carrier configured: accept the message, send nothing, and label it clearly."""

    live = False

    def __init__(self):
        self.n = 0

    def send_sms(self, frm, to, body):
        self.n += 1
        return f"DRYRUN{int(time.time())}{self.n:03d}"


class TwilioCarrier(Carrier):
    live = True

    def __init__(self, sid: str, token: str, post=None):
        self.sid, self.token = sid, token
        self.post = post or self._post

    def _post(self, url: str, form: dict, auth: str) -> dict:
        req = urllib.request.Request(
            url, data=urllib.parse.urlencode(form).encode(), headers={"Authorization": f"Basic {auth}"}
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            with e:
                detail = e.read()[:300].decode("utf-8", "replace")
            raise TelcoError(f"carrier rejected the message (HTTP {e.code}): {detail}") from None
        except OSError as e:
            raise TelcoError(f"carrier unreachable: {e}") from None

    def send_sms(self, frm, to, body):
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}/Messages.json"
        auth = base64.b64encode(f"{self.sid}:{self.token}".encode()).decode()
        return self.post(url, {"From": frm, "To": to, "Body": body}, auth)["sid"]


def carrier_from_env(env=None) -> Carrier:
    env = os.environ if env is None else env
    sid, token = env.get("TWILIO_ACCOUNT_SID", ""), env.get("TWILIO_AUTH_TOKEN", "")
    return TwilioCarrier(sid, token) if sid and token else DryRunCarrier()


class Service:
    def __init__(self, store: str, carrier: Carrier | None = None, clock=time.time):
        self.store, self.clock = store, clock
        self.carrier = carrier or carrier_from_env()
        try:
            with open(store, encoding="utf-8-sig") as fh:
                doc = json.load(fh)
        except FileNotFoundError:
            doc = {}
        if not isinstance(doc, dict):
            raise TelcoError(f"{store}: not an agent-telco store")
        ex = Exchange(self.carrier, doc.get("free", []), clock=clock)
        ex.numbers = dict(doc.get("numbers", {}))
        ex.owner = {num: agent for agent, num in ex.numbers.items()}
        ex.opted_out = {tuple(pair) for pair in doc.get("opted_out", [])}
        for key, msgs in doc.get("threads", {}).items():
            num, contact = key.split("|", 1)
            ex.threads[(num, contact)] = [Message(**m) for m in msgs]
        for num in ex.owner:
            bucket = TokenBucket(ex._rate, ex._burst, clock)
            saved = doc.get("buckets", {}).get(num)
            if saved:  # refill for the time that passed while we were not running
                bucket.tokens, bucket.last = float(saved["tokens"]), float(saved["last"])
            ex.buckets[num] = bucket
            ex.handlers[ex.owner[num]] = lambda msg: None  # inbound is stored in the thread; agents poll it
        self.ex = ex

    @property
    def live(self) -> bool:
        return bool(getattr(self.carrier, "live", False))

    def add_number(self, number: str) -> str:
        number = check_number(number)
        if number in self.ex.free or number in self.ex.owner:
            raise TelcoError(f"{number} is already in the pool")
        self.ex.free.append(number)
        return number

    def provision(self, agent: str, area_code: str | None = None) -> str:
        num = self.ex.provision(agent, area_code)
        self.ex.handlers[agent] = lambda msg: None
        return num

    def send(self, agent: str, to: str, body: str, marketing: bool = False, local_hour: int | None = None) -> Message:
        if not body.strip():
            raise TelcoError("message body is empty")
        return self.ex.send(agent, check_number(to), body, marketing, local_hour)

    def receive(self, to: str, frm: str, body: str) -> dict:
        to, frm = check_number(to), check_number(frm)
        if to not in self.ex.owner:
            raise TelcoError(f"{to} is not one of our provisioned numbers")
        was_out = (to, frm) in self.ex.opted_out
        msg = self.ex.receive(to, frm, body)
        now_out = (to, frm) in self.ex.opted_out
        action = "opt_out" if now_out and not was_out else "opt_in" if was_out and not now_out else msg.status
        return {"agent": self.ex.owner[to], "action": action, "otp": Exchange.extract_otp(body)}

    def save(self):
        ex = self.ex
        doc = {
            "free": ex.free,
            "numbers": ex.numbers,
            "opted_out": sorted(list(pair) for pair in ex.opted_out),
            "threads": {f"{num}|{contact}": [m.__dict__ for m in msgs] for (num, contact), msgs in ex.threads.items()},
            "buckets": {num: {"tokens": b.tokens, "last": b.last} for num, b in ex.buckets.items()},
        }
        tmp = f"{self.store}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
        os.replace(tmp, self.store)

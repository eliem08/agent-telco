"""Stateless commands: read a JSON request, print a JSON decision (also served by the web app)."""

import json

from .core import Exchange, MockCarrier, TelcoError

AGENT_NUMBER, CONTACT = "+15550000001", "+15550000002"


def add_commands(sub):
    i = sub.add_parser("inbound", help="what happens when a contact texts an agent (STOP/START, routing, OTP)")
    i.add_argument("--body", required=True)
    i.add_argument("--opted-out", action="store_true", help="the contact had already opted out")
    s = sub.add_parser("send-check", help="may an agent send this text now (opt-out, quiet hours, rate limit)")
    s.add_argument("--body", required=True)
    s.add_argument("--marketing", action="store_true")
    s.add_argument("--local-hour", type=int, help="recipient's local hour 0-23")
    s.add_argument("--opted-out", action="store_true")


def _exchange(opted_out):
    carrier = MockCarrier()
    ex = Exchange(carrier, [AGENT_NUMBER])
    ex.provision("agent")
    ex.on_inbound("agent", lambda msg: None)
    if opted_out:
        ex.opted_out.add((AGENT_NUMBER, CONTACT))
    return ex, carrier


def run(a):
    ex, carrier = _exchange(a.opted_out)
    if a.cmd == "inbound":
        was_out = (AGENT_NUMBER, CONTACT) in ex.opted_out
        msg = ex.receive(AGENT_NUMBER, CONTACT, a.body)
        now_out = (AGENT_NUMBER, CONTACT) in ex.opted_out
        action = "opt_out" if now_out and not was_out else "opt_in" if was_out and not now_out else msg.status
        out = {
            "action": action,
            "auto_reply": carrier.outbox[-1][2] if carrier.outbox else None,
            "otp": Exchange.extract_otp(a.body),
        }
        print(json.dumps(out, indent=2))
        return 0
    try:
        ex.send("agent", CONTACT, a.body, a.marketing, a.local_hour)
    except TelcoError as e:
        print(json.dumps({"allowed": False, "reason": str(e)}, indent=2))
        return 1
    print(json.dumps({"allowed": True}, indent=2))
    return 0

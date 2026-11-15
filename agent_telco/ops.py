"""Operating commands: run a real exchange against a persistent store (also served by the web app)."""

import os

from .core import TelcoError
from .service import Service

OPS = ("number-add", "provision", "release", "numbers", "send", "receive", "thread")


def add_ops(sub):
    store = os.environ.get("AGENT_TELCO_STORE", "telco.json")
    p = sub.add_parser("number-add", help="add a phone number you own to the pool")
    p.add_argument("number", help="E.164, e.g. +14155550100")
    p = sub.add_parser("provision", help="give an agent its own number")
    p.add_argument("agent")
    p.add_argument("--area-code")
    p = sub.add_parser("release", help="take an agent's number back into the pool")
    p.add_argument("agent")
    sub.add_parser("numbers", help="list the pool and who owns what")
    p = sub.add_parser("send", help="send a text as an agent (opt-outs, quiet hours and rate limits enforced)")
    p.add_argument("agent")
    p.add_argument("to")
    p.add_argument("--body", required=True)
    p.add_argument("--marketing", action="store_true")
    p.add_argument("--local-hour", type=int, help="recipient's local hour 0-23")
    p = sub.add_parser("receive", help="record an inbound text (wire your carrier webhook to this)")
    p.add_argument("--to", required=True, help="our number")
    p.add_argument("--from", dest="frm", required=True, help="the contact")
    p.add_argument("--body", required=True)
    p = sub.add_parser("thread", help="the conversation between an agent and a contact")
    p.add_argument("agent")
    p.add_argument("contact")
    for name in OPS:
        sub.choices[name].add_argument("--store", default=store)


def run_ops(a) -> int:
    try:
        svc = Service(a.store)
        code = _run(svc, a)
        svc.save()
        return code
    except TelcoError as e:
        print(f"refused: {e}")
        return 1


def _run(svc: Service, a) -> int:
    ex = svc.ex
    if a.cmd == "number-add":
        print(f"added {svc.add_number(a.number)}; {len(ex.free)} free")
    elif a.cmd == "provision":
        print(f"{a.agent} -> {svc.provision(a.agent, a.area_code)}")
    elif a.cmd == "release":
        if a.agent not in ex.numbers:
            raise TelcoError(f"agent {a.agent!r} has no number")
        num = ex.numbers[a.agent]
        ex.release(a.agent)
        print(f"released {num} from {a.agent}")
    elif a.cmd == "numbers":
        for agent, num in sorted(ex.numbers.items()):
            print(f"{num}  {agent}")
        for num in ex.free:
            print(f"{num}  (free)")
        if not ex.numbers and not ex.free:
            print("no numbers yet: add one with number-add")
        print(f"carrier: {'Twilio (live)' if svc.live else 'none configured: sends are recorded, not delivered'}")
    elif a.cmd == "send":
        msg = svc.send(a.agent, a.to, a.body, a.marketing, a.local_hour)
        print(f"{'sent' if svc.live else 'recorded (dry run, no carrier configured)'} {msg.sid} to {msg.contact}")
    elif a.cmd == "receive":
        r = svc.receive(a.to, a.frm, a.body)
        print(f"{r['action']} for {r['agent']}" + (f"; otp {r['otp']}" if r["otp"] else ""))
    else:
        if a.agent not in ex.numbers:
            raise TelcoError(f"agent {a.agent!r} has no number")
        msgs = ex.thread(a.agent, a.contact)
        for m in msgs:
            print(f"{'>>' if m.direction == 'out' else '<<'} {m.body}")
        if not msgs:
            print("no messages yet")
    return 0

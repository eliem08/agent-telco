import argparse
import sys

from .core import Exchange, MockCarrier, TelcoError


def demo():
    carrier = MockCarrier()
    ex = Exchange(carrier, pool=["+14155550100", "+12125550101", "+13105550102"])
    num = ex.provision("booking-agent", area_code="212")
    print(f"provisioned {num} for booking-agent")
    ex.on_inbound("booking-agent", lambda m: print(f"  [booking-agent] inbound from {m.contact}: {m.body!r} otp={ex.extract_otp(m.body)}"))
    ex.send("booking-agent", "+12125559999", "Hi! Can I book a table for 2 at 7pm?")
    ex.receive(num, "+12125559999", "Yes - confirmation code 482913")
    ex.receive(num, "+12125559999", "STOP")
    try:
        ex.send("booking-agent", "+12125559999", "Reminder!")
    except TelcoError as e:
        print(f"  blocked: {e}")
    print("carrier outbox:")
    for frm, to, body in carrier.outbox:
        print(f"  {frm} -> {to}: {body}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="agent-telco")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo", help="run an end-to-end example with the mock carrier")
    ap.parse_args(argv)
    demo()
    return 0


if __name__ == "__main__":
    sys.exit(main())

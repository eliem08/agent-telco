<!-- sell-kit:start -->
# Agent Telco

[![CI](https://github.com/eliem08/agent-telco/actions/workflows/ci.yml/badge.svg)](https://github.com/eliem08/agent-telco/actions/workflows/ci.yml)

> **Phone numbers and compliant texting for AI agents.**

**Who it's for:** Developers building agents that need to send and receive SMS.

**The problem:** Giving agents a phone number means handling opt-outs, quiet hours, rate limits and routing replies, and getting any of it wrong breaks the law.

**What you get:** A number pool, compliant outbound SMS (STOP handling, quiet hours, rate limits), inbound routing to the right agent and OTP extraction.

## Quickstart

Customers receive a release archive with the wheel and the examples. Python 3.10+ and no other dependencies.

```bash
pip install agent_telco-0.1.0-py3-none-any.whl
agent-telco demo
```

## Pricing

Every plan starts with a 14-day free trial. Prices in USD, billed monthly unless noted.

| Plan | Price | Includes |
|---|---|---|
| **Starter** | $29 per month + carrier fees | 5 numbers; Opt-out and quiet-hours compliance; Inbound routing |
| **Growth** | $149 per month + carrier fees | 50 numbers; Per-number rate limits; Message threads export |
| **Scale** | $599 per month + carrier fees | Unlimited numbers; Compliance reports; Priority support |

To start a trial or buy a plan, email **sales@YOUR-DOMAIN.com**.

## Licence

Proprietary. Copyright (c) 2026 eliem08. All rights reserved. Use requires a paid plan or an active trial; see [LICENSE](LICENSE).
<!-- sell-kit:end -->

## What it does

- **Number provisioning** from a pool, by preferred area code; release back to the pool
- **Outbound SMS** through a `Carrier` interface (`MockCarrier` ships; plug in
  Twilio / Telnyx / Bandwidth adapters)
- **Compliance**: STOP / UNSUBSCRIBE / START keywords, opt-out list enforced on send,
  quiet hours (no marketing texts 21:00–08:00 recipient local time)
- **Rate limiting**: token bucket per number (default 1 msg/sec, burst 5)
- **Inbound routing** to the owning agent's handler (+ OTP code extraction helper)
- Full conversation threads per (agent number, contact)

## Quickstart

```python
from agent_telco import Exchange, MockCarrier

ex = Exchange(MockCarrier(), pool=["+14155550100", "+12125550101"])
num = ex.provision("booking-agent", area_code="415")
ex.on_inbound("booking-agent", lambda msg: print("got", msg.body, ex.extract_otp(msg.body)))
ex.send("booking-agent", to="+14155559999", body="Table for 2 at 7pm?")
ex.receive(to=num, frm="+14155559999", body="Confirmed. Code 482913")
```

```bash
agent-telco demo
```

## Roadmap

- Real carrier adapters + 10DLC brand/campaign registration
- Voice: SIP trunk + realtime speech agents
- Per-agent number reputation and spam-label monitoring
- Email + WhatsApp channels behind the same API

## Development

Zero runtime dependencies; Python 3.10+.

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m unittest discover -s tests -t .           # unit + CLI smoke tests
ruff check . && ruff format --check .               # lint + format
```

```
agent_telco/core.py       domain logic (pure, importable, fully tested)
agent_telco/__main__.py   CLI (`agent-telco ...` / `python -m agent_telco ...`)
tests/                unit tests + generated CLI smoke tests
```

CI runs lint and tests on Ubuntu and Windows across Python 3.10, 3.12 and 3.13.
Design, data model, trade-offs and production path: **[ARCHITECTURE.md](ARCHITECTURE.md)**.

Part of the [agent-economy](https://github.com/eliem08/agent-economy) portfolio (idea #9).

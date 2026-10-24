# agent-telco

> **Twilio for agents** — phone numbers and texting for agents.

Agents need to receive 2FA codes, text customers back, confirm a booking with
a restaurant. Giving every agent a real, compliant phone identity is fiddly:
number pools, opt-outs, rate limits, routing inbound texts to the right agent.
`agent-telco` is that layer, with a pluggable carrier backend.

## What the MVP does

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

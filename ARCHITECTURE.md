# Architecture — agent-telco

## 1. Scope
Compliant phone identities for agents: number provisioning, outbound SMS, inbound routing, opt-outs, rate limits.
**MVP:** in-memory exchange with pluggable `Carrier`, number pool, STOP/START handling, quiet hours, token-bucket limits, OTP extraction, threads.
**Product:** multi-carrier API (Twilio, Telnyx, Bandwidth adapters), 10DLC registration, voice, number reputation.

## 2. System context
```mermaid
flowchart LR
  Agent -->|send(agent, to, body)| Exchange
  Exchange -->|compliance + rate limit| Carrier[Carrier adapter]
  Carrier -->|SMS| Phone[Recipient]
  Phone -->|reply| Carrier -->|webhook| Exchange
  Exchange -->|route by owned number| Handler[Agent webhook / callback]
```

## 3. Components
| Module | Responsibility | Status |
|---|---|---|
| `Exchange.provision/release` | Pool allocation with area-code preference, idempotent per agent | MVP |
| `Exchange.send` | Opt-out check → quiet hours (marketing only) → token bucket → carrier | MVP |
| `Exchange.receive` | STOP/START keywords (auto-reply), route to owner handler, else `unrouted` | MVP |
| `TokenBucket` | Per-number rate limit with injectable clock | MVP |
| `Carrier` / `MockCarrier` | Adapter interface | MVP |

## 4. Design decisions
- **Compliance in the exchange, not the agent.** Agents can't be trusted to honour STOP, so it is
  enforced centrally before any carrier call.
- **Opt-out keyed by (agent number, contact).** This matches carrier semantics, where opting out of
  one sender doesn't block others.
- **Injectable clock** for deterministic rate-limit tests.
- **Ordering of checks:** opt-out → quiet hours → rate limit. Cheap, legally mandatory checks come
  first, and a blocked message doesn't consume a rate token.

## 5. Production architecture
- API + Postgres (numbers, agents, opt-outs, messages). Redis token buckets (atomic Lua) shared across replicas.
- Inbound webhooks verified with carrier signatures, with an idempotency key on the carrier message SID.
- Outbound queue with retries and exponential backoff. Carrier failover on 5xx.
- 10DLC: brand and campaign registry per customer, and numbers bound to campaigns.

## 6. Security & abuse
- KYC for customers before provisioning. Per-tenant daily caps. Content scanning for phishing
  (reuse scam-shield rules).
- Number reputation monitoring (carrier spam labels) with automatic quarantine.

## 7. Risks
Carrier policy shifts on A2P traffic from AI. Mitigate by staying carrier-agnostic and keeping
compliance-first defaults.

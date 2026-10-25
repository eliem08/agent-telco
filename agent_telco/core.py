"""Number pool, compliant outbound SMS, rate limits and inbound routing for agents."""

from __future__ import annotations

import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

__all__ = ["Message", "Carrier", "MockCarrier", "Exchange", "TelcoError", "TokenBucket"]

STOP_WORDS = {"stop", "stopall", "unsubscribe", "cancel", "end", "quit"}
START_WORDS = {"start", "unstop", "yes"}
OTP_RE = re.compile(r"\b(\d{4,8})\b")


class TelcoError(Exception):
    pass


@dataclass
class Message:
    direction: str
    agent_number: str
    contact: str
    body: str
    ts: float = field(default_factory=time.time)
    status: str = "queued"
    sid: str = ""


class Carrier:
    def send_sms(self, frm: str, to: str, body: str) -> str:
        raise NotImplementedError


class MockCarrier(Carrier):
    def __init__(self):
        self.outbox: list[tuple[str, str, str]] = []

    def send_sms(self, frm, to, body):
        self.outbox.append((frm, to, body))
        return f"SM{len(self.outbox):06d}"


class TokenBucket:
    def __init__(self, rate: float = 1.0, burst: int = 5, clock=time.monotonic):
        self.rate, self.burst, self.clock = rate, burst, clock
        self.tokens, self.last = float(burst), clock()

    def take(self) -> bool:
        now = self.clock()
        self.tokens = min(self.burst, self.tokens + (now - self.last) * self.rate)
        self.last = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


class Exchange:
    def __init__(self, carrier: Carrier, pool: list[str], rate: float = 1.0, burst: int = 5, clock=time.monotonic):
        self.carrier = carrier
        self.free = list(pool)
        self.owner: dict[str, str] = {}  # number -> agent
        self.numbers: dict[str, str] = {}  # agent -> number
        self.handlers: dict[str, callable] = {}
        self.opted_out: set[tuple[str, str]] = set()  # (agent_number, contact)
        self.threads: dict[tuple[str, str], list[Message]] = defaultdict(list)
        self.buckets: dict[str, TokenBucket] = {}
        self._rate, self._burst, self._clock = rate, burst, clock

    # numbers -----------------------------------------------------------
    def provision(self, agent: str, area_code: str | None = None) -> str:
        if agent in self.numbers:
            return self.numbers[agent]
        if not self.free:
            raise TelcoError("number pool exhausted")
        pick = next((n for n in self.free if area_code and n.removeprefix("+1").startswith(area_code)), self.free[0])
        self.free.remove(pick)
        self.owner[pick], self.numbers[agent] = agent, pick
        self.buckets[pick] = TokenBucket(self._rate, self._burst, self._clock)
        return pick

    def release(self, agent: str):
        num = self.numbers.pop(agent)
        del self.owner[num]
        self.handlers.pop(agent, None)
        self.free.append(num)

    def on_inbound(self, agent: str, handler):
        self.handlers[agent] = handler

    # messaging ---------------------------------------------------------
    def send(self, agent: str, to: str, body: str, marketing: bool = False, local_hour: int | None = None) -> Message:
        num = self.numbers.get(agent)
        if not num:
            raise TelcoError(f"agent {agent!r} has no number")
        if (num, to) in self.opted_out:
            raise TelcoError(f"{to} opted out of {num}")
        if local_hour is not None and not (isinstance(local_hour, int) and 0 <= local_hour <= 23):
            raise TelcoError(f"local_hour must be 0-23, got {local_hour!r}")
        hour = datetime.now().hour if local_hour is None else local_hour
        if marketing and (hour >= 21 or hour < 8):
            raise TelcoError("quiet hours: marketing messages blocked 21:00-08:00")
        if not self.buckets[num].take():
            raise TelcoError("rate limited")
        msg = Message("out", num, to, body)
        msg.sid = self.carrier.send_sms(num, to, body)
        msg.status = "sent"
        self.threads[(num, to)].append(msg)
        return msg

    def receive(self, to: str, frm: str, body: str) -> Message:
        agent = self.owner.get(to)
        msg = Message("in", to, frm, body, status="received")
        self.threads[(to, frm)].append(msg)
        # carriers honour "STOP.", "Stop please", "stop!!" - match the keyword, not the exact body
        words = re.findall(r"[a-z]+", body.lower())
        word = words[0] if words else ""
        if word in STOP_WORDS:
            self.opted_out.add((to, frm))
            self.carrier.send_sms(to, frm, "You are unsubscribed. Reply START to resubscribe.")
            return msg
        if word in START_WORDS and (to, frm) in self.opted_out:
            self.opted_out.discard((to, frm))
            self.carrier.send_sms(to, frm, "You are resubscribed.")
            return msg
        if agent and agent in self.handlers:
            self.handlers[agent](msg)
        else:
            msg.status = "unrouted"
        return msg

    def thread(self, agent: str, contact: str) -> list[Message]:
        return self.threads.get((self.numbers[agent], contact), [])

    @staticmethod
    def extract_otp(body: str) -> str | None:
        m = OTP_RE.search(body)
        return m.group(1) if m else None

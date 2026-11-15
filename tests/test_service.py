import contextlib
import io
import os
import tempfile
import unittest

from agent_telco.__main__ import main
from agent_telco.core import TelcoError
from agent_telco.service import DryRunCarrier, Service, TwilioCarrier, carrier_from_env, check_number

US, THEM = "+14155550100", "+12125559999"


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = main(list(argv))
    return code, out.getvalue()


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = os.path.join(self.tmp.name, "telco.json")

    def tearDown(self):
        self.tmp.cleanup()

    def fresh(self, **kw):
        return Service(self.store, **kw)

    def test_state_survives_a_restart(self):
        svc = self.fresh()
        svc.add_number(US)
        svc.provision("booking")
        svc.send("booking", THEM, "hello")
        svc.receive(US, THEM, "STOP")
        svc.save()
        again = self.fresh()
        self.assertEqual(again.ex.numbers, {"booking": US})
        self.assertEqual([m.body for m in again.ex.thread("booking", THEM)], ["hello", "STOP"])
        with self.assertRaises(TelcoError):  # the opt-out is still honoured after a restart
            again.send("booking", THEM, "one more thing")

    def test_rate_limit_is_not_reset_by_restarting(self):
        now = [1000.0]
        svc = self.fresh(clock=lambda: now[0])
        svc.add_number(US)
        svc.provision("a")
        for i in range(5):
            svc.send("a", THEM, f"m{i}")
        svc.save()
        again = self.fresh(clock=lambda: now[0])
        with self.assertRaises(TelcoError):
            again.send("a", THEM, "burst")
        now[0] += 10  # tokens refill with real time
        self.fresh(clock=lambda: now[0]).send("a", THEM, "later")

    def test_twilio_carrier_posts_the_message_and_dry_run_never_claims_delivery(self):
        calls = []

        def post(url, form, auth):
            calls.append((url, form))
            return {"sid": "SM123"}

        svc = self.fresh(carrier=TwilioCarrier("ACx", "tok", post=post))
        svc.add_number(US)
        svc.provision("a")
        self.assertEqual(svc.send("a", THEM, "hi").sid, "SM123")
        self.assertIn("/Accounts/ACx/Messages.json", calls[0][0])
        self.assertEqual(calls[0][1], {"From": US, "To": THEM, "Body": "hi"})
        self.assertTrue(svc.live)
        self.assertIsInstance(carrier_from_env({}), DryRunCarrier)
        self.assertIsInstance(carrier_from_env({"TWILIO_ACCOUNT_SID": "a", "TWILIO_AUTH_TOKEN": "b"}), TwilioCarrier)

    def test_numbers_are_validated(self):
        self.assertEqual(check_number("+1 (415) 555-0100"), US)
        for bad in ("4155550100", "+1212", "tel:+14155550100", ""):
            with self.subTest(bad=bad), self.assertRaises(TelcoError):
                check_number(bad)

    def test_cli_journey(self):
        s = ["--store", self.store]
        self.assertEqual(run("number-add", US, *s)[0], 0)
        self.assertEqual(run("provision", "booking", *s)[0], 0)
        code, out = run("send", "booking", THEM, "--body", "Table for 2?", *s)
        self.assertEqual(code, 0)
        self.assertIn("dry run", out)
        self.assertIn("otp 482913", run("receive", "--to", US, "--from", THEM, "--body", "code 482913", *s)[1])
        run("receive", "--to", US, "--from", THEM, "--body", "Stop please", *s)
        code, out = run("send", "booking", THEM, "--body", "Reminder", *s)
        self.assertEqual((code, "opted out" in out), (1, True))
        self.assertEqual(run("send", "nobody", THEM, "--body", "x", *s)[0], 1)
        self.assertIn("<< Stop please", run("thread", "booking", THEM, *s)[1])


if __name__ == "__main__":
    unittest.main()

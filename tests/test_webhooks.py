"""Twilio webhooks: signature checks, inbound texts, STOP/START, retries and delivery reports, over real HTTP."""

import os
import pathlib
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest import mock

from agent_telco.core import TelcoError
from agent_telco.routes import STORE_FILE, twilio_signature
from agent_telco.service import FINAL, Service, TwilioCarrier, carrier_from_env, store_lock
from agent_telco.web import make_server

US, THEM = "+14155550100", "+12125559999"
TOKEN, PUBLIC = "test-auth-token", "https://telco.example.com"


class SignatureTests(unittest.TestCase):
    def test_matches_twilios_published_example(self):
        # https://www.twilio.com/docs/usage/security (token 12345)
        params = {
            "CallSid": ["CA1234567890ABCDE"],
            "Caller": ["+14158675310"],
            "Digits": ["1234"],
            "From": ["+14158675310"],
            "To": ["+18005551212"],
        }
        sig = twilio_signature("12345", "https://example.com/myapp.php?foo=1&bar=2", params)
        self.assertEqual(sig, "L/OH5YylLD5NRKLltdqwSvS0BnU=")


class WebhookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = pathlib.Path(self.tmp.name)
        self.store = str(self.data / STORE_FILE)
        env = {"TWILIO_AUTH_TOKEN": TOKEN, "PUBLIC_URL": PUBLIC, "API_KEYS": "sk_test_only"}
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()
        os.environ.pop("TWILIO_ACCOUNT_SID", None)  # sends stay dry runs
        svc = Service(self.store)
        svc.add_number(US)
        svc.provision("booking")
        self.sent = svc.send("booking", THEM, "Your table is booked")
        svc.save()
        self.srv = make_server("127.0.0.1", 0, self.data, "sk_test_only")
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.env.stop()
        self.tmp.cleanup()

    def post(self, path, form, sign=True, sig=None):
        body = urllib.parse.urlencode(form).encode()
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if sign:
            params = {k: [v] for k, v in form.items()}
            headers["X-Twilio-Signature"] = sig or twilio_signature(TOKEN, PUBLIC + path, params)
        req = urllib.request.Request(self.base + path, data=body, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.read().decode()

    def text(self, body, sid):
        return self.post("/twilio/inbound", {"MessageSid": sid, "From": THEM, "To": US, "Body": body})

    def thread(self):
        return Service(self.store).ex.thread("booking", THEM)

    def test_unsigned_or_forged_requests_change_nothing(self):
        form = {"MessageSid": "SM1", "From": THEM, "To": US, "Body": "STOP"}
        self.assertEqual(self.post("/twilio/inbound", form, sign=False)[0], 403)
        self.assertEqual(self.post("/twilio/inbound", form, sig="AAAA")[0], 403)
        # signed for a different body: tampering is caught
        forged = twilio_signature(
            TOKEN, PUBLIC + "/twilio/inbound", {k: [v] for k, v in {**form, "Body": "hi"}.items()}
        )
        self.assertEqual(self.post("/twilio/inbound", form, sig=forged)[0], 403)
        self.assertEqual(len(self.thread()), 1)
        Service(self.store).send("booking", THEM, "still allowed")  # no opt-out was recorded

    def test_not_configured_refuses(self):
        os.environ.pop("TWILIO_AUTH_TOKEN")
        self.assertEqual(self.text("hi", "SM1")[0], 503)
        os.environ["TWILIO_AUTH_TOKEN"], os.environ["PUBLIC_URL"] = TOKEN, "http://insecure.example.com"
        self.assertEqual(self.text("hi", "SM1")[0], 503)

    def test_inbound_text_lands_in_the_thread_once(self):
        status, body = self.text("Your code is 482913", "SM100")
        self.assertEqual(status, 200)
        self.assertIn("<Response>", body)
        self.assertEqual(self.text("Your code is 482913", "SM100")[0], 200)  # Twilio retry
        msgs = self.thread()
        self.assertEqual([m.body for m in msgs], ["Your table is booked", "Your code is 482913"])
        self.assertEqual(msgs[1].sid, "SM100")

    def test_stop_blocks_sending_and_start_lifts_it(self):
        self.assertEqual(self.text("Stop please", "SM2")[0], 200)
        self.assertEqual([m.direction for m in self.thread()], ["out", "in"])  # Twilio confirms; we do not
        with self.assertRaises(TelcoError):
            Service(self.store).send("booking", THEM, "promo")
        self.assertEqual(self.text("START", "SM3")[0], 200)
        Service(self.store).send("booking", THEM, "welcome back")

    def test_text_to_a_number_we_do_not_own_is_refused(self):
        status, _ = self.post("/twilio/inbound", {"MessageSid": "SM4", "From": THEM, "To": "+13105550000", "Body": "x"})
        self.assertEqual(status, 400)

    def test_delivery_reports_update_the_sent_message(self):
        def report(state, code=""):
            form = {"MessageSid": self.sent.sid, "MessageStatus": state}
            if code:
                form["ErrorCode"] = code
            return self.post("/twilio/status", form)[0]

        self.assertEqual(report("delivered"), 200)
        self.assertEqual(self.thread()[0].status, "delivered")
        self.assertEqual(report("sent"), 200)  # out-of-order callback does not undo a final state
        self.assertEqual(self.thread()[0].status, "delivered")
        self.assertEqual(report("failed", "30003"), 200)
        self.assertEqual(self.thread()[0].status, "failed (30003)")
        self.assertEqual(self.post("/twilio/status", {"MessageSid": "SMunknown", "MessageStatus": "sent"})[0], 200)

    def test_api_keys_still_guard_the_api(self):
        req = urllib.request.Request(self.base + "/api/numbers", data=b"{}")
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(e.exception.code, 401)


class CarrierAndLockTests(unittest.TestCase):
    def test_status_callback_is_sent_only_with_an_https_public_url(self):
        env = {"TWILIO_ACCOUNT_SID": "AC1", "TWILIO_AUTH_TOKEN": "t", "PUBLIC_URL": PUBLIC + "/"}
        self.assertEqual(carrier_from_env(env).status_callback, PUBLIC + "/twilio/status")
        self.assertEqual(carrier_from_env({**env, "PUBLIC_URL": "http://x.example"}).status_callback, "")
        forms = []
        c = TwilioCarrier(
            "AC1",
            "t",
            post=lambda url, form, auth: forms.append(form) or {"sid": "SM9"},
            status_callback=PUBLIC + "/twilio/status",
        )
        c.send_sms(US, THEM, "hi")
        self.assertEqual(forms[0]["StatusCallback"], PUBLIC + "/twilio/status")
        self.assertIn("delivered", FINAL)

    def test_store_lock_is_exclusive_and_released(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = os.path.join(tmp, "s.json")
            with store_lock(store), self.assertRaises(TelcoError), store_lock(store, timeout=0.2):
                pass
            with store_lock(store):  # released after the first block
                pass
            self.assertFalse(os.path.exists(store + ".lock"))


if __name__ == "__main__":
    unittest.main()

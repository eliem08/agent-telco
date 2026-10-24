import unittest

from agent_telco import Exchange, MockCarrier, TelcoError


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class Tests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.c = MockCarrier()
        self.ex = Exchange(self.c, ["+14155550100", "+12125550101"], rate=1, burst=2, clock=self.clock)

    def test_provision_by_area_code_and_exhaustion(self):
        self.assertEqual(self.ex.provision("a", "212"), "+12125550101")
        self.assertEqual(self.ex.provision("a"), "+12125550101")  # idempotent
        self.ex.provision("b")
        with self.assertRaises(TelcoError):
            self.ex.provision("c")
        self.ex.release("b")
        self.assertEqual(self.ex.provision("c"), "+14155550100")

    def test_inbound_routing_and_otp(self):
        num = self.ex.provision("a")
        got = []
        self.ex.on_inbound("a", got.append)
        self.ex.receive(num, "+1999", "Your code is 123456")
        self.assertEqual(Exchange.extract_otp(got[0].body), "123456")
        self.assertEqual(self.ex.receive("+10000000000", "+1999", "hi").status, "unrouted")

    def test_stop_start(self):
        num = self.ex.provision("a")
        self.ex.receive(num, "+1999", "STOP")
        with self.assertRaises(TelcoError):
            self.ex.send("a", "+1999", "hello")
        self.ex.receive(num, "+1999", "start")
        self.assertEqual(self.ex.send("a", "+1999", "hello").status, "sent")

    def test_rate_limit_and_quiet_hours(self):
        self.ex.provision("a")
        self.ex.send("a", "+1", "1")
        self.ex.send("a", "+1", "2")
        with self.assertRaises(TelcoError):
            self.ex.send("a", "+1", "3")
        self.clock.t += 1.0
        self.ex.send("a", "+1", "4")
        with self.assertRaises(TelcoError):
            self.ex.send("a", "+2", "promo", marketing=True, local_hour=22)
        self.assertEqual(len(self.ex.thread("a", "+1")), 3)


if __name__ == "__main__":
    unittest.main()

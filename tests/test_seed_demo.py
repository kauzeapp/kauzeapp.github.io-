import unittest
from datetime import date

from backend.seed_demo import DEMO_NAME, DEMO_SLUG, build_panel_state


class DemoSeedTests(unittest.TestCase):
    def setUp(self):
        self.state = build_panel_state(date(2026, 7, 17))

    def test_demo_is_clearly_isolated(self):
        self.assertEqual(DEMO_NAME, "Barbería Cauce Norte — DEMO")
        self.assertEqual(DEMO_SLUG, "barberia-cauce-norte-demo")
        self.assertTrue(self.state["demoMode"])
        self.assertFalse(self.state["externalMessagingEnabled"])
        self.assertFalse(
            self.state["notificationPreferences"]["externalDeliveryEnabled"]
        )

    def test_demo_contains_expected_operational_data(self):
        self.assertEqual(len(self.state["professionals"]["barberia"]), 3)
        self.assertEqual(len(self.state["services"]["barberia"]), 4)
        self.assertEqual(len(self.state["clients"]["barberia"]), 3)
        self.assertEqual(len(self.state["appointments"]["barberia"]), 4)
        self.assertEqual(len(self.state["virtualQueue"]), 2)

    def test_demo_has_no_real_delivery_targets(self):
        self.assertEqual(self.state["ownerWhatsapp"], "")
        self.assertEqual(self.state["ownerCalendarEmail"], "")
        for client in self.state["clients"]["barberia"]:
            self.assertIn("DEMO", client["phone"])


if __name__ == "__main__":
    unittest.main()

import unittest

from backend.auth import (
    AccountUnavailable,
    BusinessSelectionRequired,
    _select_membership,
)


def membership(slug, *, superadmin=False):
    return {
        "local_nombre": slug.title(),
        "local_slug": slug,
        "rol_nombre": "Dueño",
        "categoria_slug": "barberia",
        "is_superadmin": superadmin,
    }


class AuthMembershipSelectionTests(unittest.TestCase):
    def test_superadmin_with_multiple_businesses_enters_directly(self):
        rows = [membership("primero"), membership("segundo", superadmin=True)]

        selected = _select_membership(rows)

        self.assertEqual(selected["local_slug"], "segundo")

    def test_owner_with_multiple_businesses_must_choose(self):
        rows = [membership("primero"), membership("segundo")]

        with self.assertRaises(BusinessSelectionRequired) as context:
            _select_membership(rows)

        self.assertEqual(len(context.exception.businesses), 2)

    def test_requested_unknown_business_is_rejected(self):
        with self.assertRaises(AccountUnavailable):
            _select_membership([membership("primero")], "inexistente")


if __name__ == "__main__":
    unittest.main()

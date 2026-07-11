from __future__ import annotations

import unittest
from unittest.mock import patch

from accounting_agent.client_identity import (
    canonical_client_id,
    client_id_from_storage_key,
    client_storage_key,
)


class ClientIdentityTests(unittest.TestCase):
    def test_cjk_compatibility_ideograph_has_stable_canonical_storage_key(self) -> None:
        compatibility_ideograph = "\U0002f800"
        canonical_ideograph = "\u4e3d"
        expected_storage_key = "v1-4s4l2"

        self.assertEqual(canonical_ideograph, canonical_client_id(compatibility_ideograph))
        self.assertEqual(expected_storage_key, client_storage_key(compatibility_ideograph))
        self.assertEqual(expected_storage_key, client_storage_key(canonical_ideograph))
        self.assertEqual(
            canonical_ideograph,
            client_id_from_storage_key(expected_storage_key),
        )

    def test_python_314_rejects_surrogate_pair_before_nfc_normalization(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "control or invisible format characters",
        ):
            canonical_client_id("\ud87e\udc00")

    def test_category_c_validation_precedes_nfc_normalization(self) -> None:
        with patch(
            "accounting_agent.client_identity.unicodedata.normalize",
            return_value="\u4e3d",
        ) as normalize:
            with self.assertRaisesRegex(
                ValueError,
                "control or invisible format characters",
            ):
                canonical_client_id("\ud87e\udc00")

        normalize.assert_not_called()


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from unittest.mock import patch

from accounting_agent.client_identity import canonical_client_id


class ClientIdentityTests(unittest.TestCase):
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

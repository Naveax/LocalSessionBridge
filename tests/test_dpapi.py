from __future__ import annotations

import os

import pytest

from broker.session_bridge import Protector


@pytest.mark.skipif(os.name != "nt", reason="Windows current-user DPAPI test")
def test_current_user_dpapi_roundtrip() -> None:
    protector = Protector(test_plaintext=False)
    secret = "local-session-bridge-dpapi-test"
    protected = protector.protect(secret)
    assert protected.startswith("dpapi:")
    assert secret not in protected
    assert protector.unprotect(protected) == secret

from broker.session_bridge import selftest_once


def test_local_runtime_suite() -> None:
    assert len(selftest_once()) == 10

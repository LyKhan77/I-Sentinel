"""Tes murni `zone_delivery`: turunan delivery, kedaluwarsa Mode uji, dan stempel server."""
from datetime import datetime, timedelta, timezone

from app.services.zone_delivery import TEST_HOURS, effective_delivery, stamp_test_mode

NOW = datetime(2026, 10, 12, 8, 0, 0, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# --- effective_delivery -----------------------------------------------------

def test_derives_from_item_telegram_then_zone_flag():
    assert effective_delivery({"kind": "intrusion", "telegram": True}, False, NOW) == "all"
    assert effective_delivery({"kind": "intrusion", "telegram": False}, True, NOW) == "inbox"
    # item tanpa key → flag zona; zona pra-R5 (behaviors None) → flag zona
    assert effective_delivery({"kind": "intrusion"}, True, NOW) == "all"
    assert effective_delivery({"kind": "intrusion"}, False, NOW) == "inbox"
    assert effective_delivery(None, True, NOW) == "all"
    assert effective_delivery(None, False, NOW) == "inbox"


def test_all_and_inbox_are_returned_as_is():
    assert effective_delivery({"kind": "intrusion", "delivery": "all"}, False, NOW) == "all"
    assert effective_delivery({"kind": "intrusion", "delivery": "inbox"}, True, NOW) == "inbox"
    # nilai tak dikenal jatuh ke turunan telegram, bukan crash
    assert effective_delivery({"kind": "intrusion", "delivery": "x", "telegram": True}, False, NOW) == "all"


def test_test_stays_test_before_until():
    b = {"kind": "intrusion", "delivery": "test", "test_until": _iso(NOW + timedelta(hours=1)), "revert_to": "inbox"}
    assert effective_delivery(b, True, NOW) == "test"


def test_test_reverts_at_and_after_until():
    until = NOW + timedelta(hours=1)
    at = {"kind": "intrusion", "delivery": "test", "test_until": _iso(until), "revert_to": "inbox"}
    after = {"kind": "intrusion", "delivery": "test", "test_until": _iso(until), "revert_to": "inbox"}
    assert effective_delivery(at, True, until) == "inbox"
    assert effective_delivery(after, True, until + timedelta(seconds=1)) == "inbox"


def test_missing_or_unreadable_until_is_treated_as_expired():
    assert effective_delivery({"kind": "intrusion", "delivery": "test"}, True, NOW) == "all"
    assert effective_delivery(
        {"kind": "intrusion", "delivery": "test", "test_until": "besok", "revert_to": "inbox"}, True, NOW
    ) == "inbox"
    assert effective_delivery(
        {"kind": "intrusion", "delivery": "test", "test_until": None, "revert_to": "inbox"}, True, NOW
    ) == "inbox"


def test_naive_until_is_read_as_utc():
    """Node menstempel `isoformat()` dari datetime UTC beraksi; string tanpa offset tetap UTC."""
    naive = (NOW + timedelta(hours=2)).replace(tzinfo=None)
    b = {"kind": "intrusion", "delivery": "test", "test_until": naive.isoformat(), "revert_to": "all"}
    assert effective_delivery(b, True, NOW) == "test"


# --- stamp_test_mode --------------------------------------------------------

def test_stamp_from_all_starts_24h_and_remembers_all():
    new = [{"kind": "intrusion", "delivery": "test", "snapshot": True, "clip": True}]
    old = [{"kind": "intrusion", "telegram": True}]
    out = stamp_test_mode(new, old, NOW)
    assert out[0]["delivery"] == "test"
    assert out[0]["test_until"] == _iso(NOW + timedelta(hours=TEST_HOURS))
    assert out[0]["revert_to"] == "all"


def test_stamp_from_inbox_remembers_inbox():
    out = stamp_test_mode([{"kind": "loitering", "delivery": "test"}], [{"kind": "loitering", "telegram": False}], NOW)
    assert out[0]["revert_to"] == "inbox"


def test_stamp_keeps_a_running_test_untouched():
    until = _iso(NOW + timedelta(hours=3))
    new = [{"kind": "intrusion", "delivery": "test", "name_extra": "x"}]
    old = [{"kind": "intrusion", "delivery": "test", "test_until": until, "revert_to": "inbox"}]
    out = stamp_test_mode(new, old, NOW)
    assert out[0]["test_until"] == until
    assert out[0]["revert_to"] == "inbox"


def test_stamp_restarts_an_expired_test():
    old = [{"kind": "intrusion", "delivery": "test", "test_until": _iso(NOW - timedelta(minutes=1)), "revert_to": "inbox"}]
    out = stamp_test_mode([{"kind": "intrusion", "delivery": "test"}], old, NOW)
    assert out[0]["test_until"] == _iso(NOW + timedelta(hours=TEST_HOURS))
    assert out[0]["revert_to"] == "inbox"  # nilai efektif sebelumnya


def test_stamp_without_old_behavior_defaults_to_all():
    out = stamp_test_mode([{"kind": "intrusion", "delivery": "test"}], None, NOW)
    assert out[0]["test_until"] == _iso(NOW + timedelta(hours=TEST_HOURS))
    assert out[0]["revert_to"] == "all"


def test_stamp_drops_test_keys_when_delivery_is_not_test():
    new = [{"kind": "intrusion", "delivery": "inbox", "test_until": _iso(NOW + timedelta(hours=5)), "revert_to": "all"}]
    out = stamp_test_mode(new, [{"kind": "intrusion", "delivery": "test"}], NOW)
    assert out[0] == {"kind": "intrusion", "delivery": "inbox"}


def test_stamp_does_not_mutate_inputs():
    new = [{"kind": "intrusion", "delivery": "test"}]
    old = [{"kind": "intrusion", "telegram": False}]
    snapshot_new = [dict(new[0])]
    snapshot_old = [dict(old[0])]
    stamp_test_mode(new, old, NOW)
    assert new == snapshot_new
    assert old == snapshot_old

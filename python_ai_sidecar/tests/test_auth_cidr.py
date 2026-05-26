"""Allow-list CIDR matching — issue #6.3.

The previous implementation did exact-string membership, so any CIDR entry
(e.g. ``172.16.0.0/12``) never matched a Docker bridge IP like
``172.18.0.5``. These tests pin the new ipaddress-based behaviour.
"""

from __future__ import annotations

from python_ai_sidecar import auth as auth_mod


def _swap_networks(monkeypatch, entries):
    monkeypatch.setattr(
        auth_mod,
        "_ALLOWED_NETWORKS",
        auth_mod._compile_allow_list(tuple(entries)),
    )


def test_empty_allowlist_allows_any_ip(monkeypatch):
    _swap_networks(monkeypatch, [])
    assert auth_mod._ip_allowed("172.18.0.5") is True
    assert auth_mod._ip_allowed("8.8.8.8") is True


def test_plain_ip_matches_exactly(monkeypatch):
    _swap_networks(monkeypatch, ["10.0.0.1"])
    assert auth_mod._ip_allowed("10.0.0.1") is True
    assert auth_mod._ip_allowed("10.0.0.2") is False


def test_cidr_v4_matches_subnet(monkeypatch):
    _swap_networks(monkeypatch, ["172.16.0.0/12"])
    # Docker bridge / overlay ranges:
    assert auth_mod._ip_allowed("172.18.0.5") is True
    assert auth_mod._ip_allowed("172.31.255.255") is True
    # Outside the /12:
    assert auth_mod._ip_allowed("10.0.0.5") is False
    assert auth_mod._ip_allowed("192.168.1.1") is False


def test_zero_zero_zero_zero_slash_zero_is_world(monkeypatch):
    _swap_networks(monkeypatch, ["0.0.0.0/0"])
    assert auth_mod._ip_allowed("1.2.3.4") is True
    assert auth_mod._ip_allowed("172.18.0.5") is True


def test_cidr_v6_matches(monkeypatch):
    _swap_networks(monkeypatch, ["fd00::/8"])
    assert auth_mod._ip_allowed("fd12:3456::1") is True
    assert auth_mod._ip_allowed("2001:db8::1") is False


def test_malformed_ip_in_request_returns_false(monkeypatch):
    _swap_networks(monkeypatch, ["172.16.0.0/12"])
    assert auth_mod._ip_allowed("not-an-ip") is False
    assert auth_mod._ip_allowed("") is False


def test_malformed_entry_is_skipped_not_fatal(monkeypatch):
    # 'banana' is invalid, 10.0.0.1 should still be honored.
    _swap_networks(monkeypatch, ["banana", "10.0.0.1"])
    assert auth_mod._ip_allowed("10.0.0.1") is True
    assert auth_mod._ip_allowed("10.0.0.2") is False


def test_multiple_entries_any_match(monkeypatch):
    _swap_networks(monkeypatch, ["127.0.0.1", "172.16.0.0/12", "::1"])
    assert auth_mod._ip_allowed("127.0.0.1") is True
    assert auth_mod._ip_allowed("172.18.0.5") is True
    assert auth_mod._ip_allowed("::1") is True
    assert auth_mod._ip_allowed("8.8.8.8") is False

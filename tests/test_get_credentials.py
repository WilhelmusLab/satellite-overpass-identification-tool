"""Tests for get_credentials function."""

import argparse
import os
import stat

import pytest

from satellite_overpass_identification_tool.app import get_credentials
from satellite_overpass_identification_tool.credentials import (
    _iter_netrc_domain_candidates,
    _normalize_domain_for_netrc,
)

DOMAIN = "space-track.org"


def test_no_credentials_returns_none(monkeypatch):
    """When no credentials are provided anywhere, both username and password are None."""
    # Remove credential env vars and set a non-existent home dir so no .netrc is found
    monkeypatch.delenv("SPACEUSER", raising=False)
    monkeypatch.delenv("SPACEPSWD", raising=False)
    monkeypatch.setenv("HOME", "/nonexistent_home_dir_xyz")

    username, password = get_credentials(DOMAIN, args=None)

    assert username is None
    assert password is None


def test_credentials_from_args():
    """Username and password are read from the args namespace."""
    args = argparse.Namespace(SPACEUSER="args_user", SPACEPSWD="args_pass")
    username, password = get_credentials(DOMAIN, args=args)
    assert username == "args_user"
    assert password == "args_pass"


def test_credentials_from_environment(monkeypatch):
    """Username and password are read from environment variables."""
    monkeypatch.setenv("SPACEUSER", "env_user")
    monkeypatch.setenv("SPACEPSWD", "env_pass")
    username, password = get_credentials(DOMAIN, args=None)
    assert username == "env_user"
    assert password == "env_pass"


def test_credentials_from_netrc(fs, monkeypatch):
    """Username and password are read from the .netrc file using a fake filesystem."""
    # Remove env vars so .netrc is consulted
    monkeypatch.delenv("SPACEUSER", raising=False)
    monkeypatch.delenv("SPACEPSWD", raising=False)

    home_dir = os.path.expanduser("~")
    netrc_content = f"machine {DOMAIN}\nlogin netrc_user\npassword netrc_pass\n"
    netrc_path = os.path.join(home_dir, ".netrc")
    fs.create_file(netrc_path, contents=netrc_content)
    os.chmod(netrc_path, stat.S_IRUSR | stat.S_IWUSR)

    username, password = get_credentials(DOMAIN, args=None)
    assert username == "netrc_user"
    assert password == "netrc_pass"


# --- Tests for _normalize_domain_for_netrc ---


@pytest.mark.parametrize(
    "input_value,expected",
    [
        ("space-track.org", "space-track.org"),
        ("www.space-track.org", "www.space-track.org"),
        ("for-testing-only.space-track.org", "for-testing-only.space-track.org"),
        ("https://www.space-track.org", "www.space-track.org"),
        ("https://www.space-track.org/ajaxauth/login", "www.space-track.org"),
        ("SPACE-TRACK.ORG", "space-track.org"),
        ("  space-track.org  ", "space-track.org"),
        ("space-track.org:443", "space-track.org"),
        ("space-track.org.", "space-track.org"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_domain_for_netrc(input_value, expected):
    """_normalize_domain_for_netrc produces a clean hostname for .netrc lookup."""
    assert _normalize_domain_for_netrc(input_value) == expected


# --- Tests for _iter_netrc_domain_candidates ---


@pytest.mark.parametrize(
    "domain,expected_candidates",
    [
        ("space-track.org", ["space-track.org"]),
        ("www.space-track.org", ["www.space-track.org", "space-track.org"]),
        (
            "for-testing-only.space-track.org",
            ["for-testing-only.space-track.org", "space-track.org"],
        ),
        (
            "https://www.space-track.org/ajaxauth/login",
            ["www.space-track.org", "space-track.org"],
        ),
    ],
)
def test_iter_netrc_domain_candidates(domain, expected_candidates):
    """_iter_netrc_domain_candidates yields hostnames from most to least specific."""
    assert list(_iter_netrc_domain_candidates(domain)) == expected_candidates


# --- Tests for subdomain fallback in get_credentials ---


def test_subdomain_falls_back_to_parent_domain_in_netrc(fs, monkeypatch):
    """www.space-track.org falls back to space-track.org .netrc credentials."""
    monkeypatch.delenv("SPACEUSER", raising=False)
    monkeypatch.delenv("SPACEPSWD", raising=False)

    home_dir = os.path.expanduser("~")
    netrc_content = "machine space-track.org\nlogin netrc_user\npassword netrc_pass\n"
    netrc_path = os.path.join(home_dir, ".netrc")
    fs.create_file(netrc_path, contents=netrc_content)
    os.chmod(netrc_path, stat.S_IRUSR | stat.S_IWUSR)

    username, password = get_credentials("www.space-track.org", args=None)
    assert username == "netrc_user"
    assert password == "netrc_pass"


def test_testing_subdomain_falls_back_to_parent_domain_in_netrc(fs, monkeypatch):
    """for-testing-only.space-track.org falls back to space-track.org .netrc credentials."""
    monkeypatch.delenv("SPACEUSER", raising=False)
    monkeypatch.delenv("SPACEPSWD", raising=False)

    home_dir = os.path.expanduser("~")
    netrc_content = "machine space-track.org\nlogin netrc_user\npassword netrc_pass\n"
    netrc_path = os.path.join(home_dir, ".netrc")
    fs.create_file(netrc_path, contents=netrc_content)
    os.chmod(netrc_path, stat.S_IRUSR | stat.S_IWUSR)

    username, password = get_credentials("for-testing-only.space-track.org", args=None)
    assert username == "netrc_user"
    assert password == "netrc_pass"


def test_url_input_resolved_via_netrc(fs, monkeypatch):
    """A full URL passed as domain is normalized and resolved against .netrc."""
    monkeypatch.delenv("SPACEUSER", raising=False)
    monkeypatch.delenv("SPACEPSWD", raising=False)

    home_dir = os.path.expanduser("~")
    netrc_content = "machine space-track.org\nlogin netrc_user\npassword netrc_pass\n"
    netrc_path = os.path.join(home_dir, ".netrc")
    fs.create_file(netrc_path, contents=netrc_content)
    os.chmod(netrc_path, stat.S_IRUSR | stat.S_IWUSR)

    username, password = get_credentials(
        "https://www.space-track.org/ajaxauth/login", args=None
    )
    assert username == "netrc_user"
    assert password == "netrc_pass"


def test_exact_subdomain_match_takes_precedence_over_parent(fs, monkeypatch):
    """An exact subdomain entry in .netrc is preferred over the parent domain entry."""
    monkeypatch.delenv("SPACEUSER", raising=False)
    monkeypatch.delenv("SPACEPSWD", raising=False)

    home_dir = os.path.expanduser("~")
    netrc_content = (
        "machine www.space-track.org\nlogin sub_user\npassword sub_pass\n"
        "machine space-track.org\nlogin parent_user\npassword parent_pass\n"
    )
    netrc_path = os.path.join(home_dir, ".netrc")
    fs.create_file(netrc_path, contents=netrc_content)
    os.chmod(netrc_path, stat.S_IRUSR | stat.S_IWUSR)

    username, password = get_credentials("www.space-track.org", args=None)
    assert username == "sub_user"
    assert password == "sub_pass"

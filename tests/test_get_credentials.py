"""Tests for get_credentials function."""

import argparse
import os
import stat

import pytest

from satellite_overpass_identification_tool.app import get_credentials

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


@pytest.mark.parametrize(
    "subdomain",
    ["www.space-track.org", "for-testing-only.space-track.org"],
)
def test_credentials_from_netrc_parent_domain_fallback(fs, monkeypatch, subdomain):
    """When the .netrc has space-track.org but not the subdomain, the parent entry is used."""
    monkeypatch.delenv("SPACEUSER", raising=False)
    monkeypatch.delenv("SPACEPSWD", raising=False)

    home_dir = os.path.expanduser("~")
    # Only the parent domain is listed in .netrc
    netrc_content = "machine space-track.org\nlogin parent_user\npassword parent_pass\n"
    netrc_path = os.path.join(home_dir, ".netrc")
    fs.create_file(netrc_path, contents=netrc_content)
    os.chmod(netrc_path, stat.S_IRUSR | stat.S_IWUSR)

    username, password = get_credentials(subdomain, args=None)
    assert username == "parent_user"
    assert password == "parent_pass"


@pytest.mark.parametrize(
    "subdomain",
    ["www.space-track.org", "for-testing-only.space-track.org"],
)
def test_credentials_from_netrc_specific_domain_takes_priority(fs, monkeypatch, subdomain):
    """When .netrc has both the specific subdomain and space-track.org, the subdomain entry wins."""
    monkeypatch.delenv("SPACEUSER", raising=False)
    monkeypatch.delenv("SPACEPSWD", raising=False)

    home_dir = os.path.expanduser("~")
    netrc_content = (
        f"machine {subdomain}\nlogin specific_user\npassword specific_pass\n"
        "machine space-track.org\nlogin parent_user\npassword parent_pass\n"
    )
    netrc_path = os.path.join(home_dir, ".netrc")
    fs.create_file(netrc_path, contents=netrc_content)
    os.chmod(netrc_path, stat.S_IRUSR | stat.S_IWUSR)

    username, password = get_credentials(subdomain, args=None)
    assert username == "specific_user"
    assert password == "specific_pass"

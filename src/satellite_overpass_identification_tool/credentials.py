"""Credential lookup helpers for space-track.org authentication."""

import netrc
import os
from urllib.parse import urlparse


netrc_message = f"""
space-track.org SPACEUSER and SPACEPSWD can be set:
- on the command line,
- as environment variables,
- or in a .netrc file.

Add the following lines to a file named .netrc in your home directory, 
replacing USERNAME and PASSWORD with your space-track.org credentials:

machine space-track.org
        login USERNAME
        password PASSWORD

For access to for-testing-only.space-track.org, 
request access from admin@space-track.org. 
        
Ensure the file has the correct permissions, 
e.g., `chmod 600 ~/.netrc` on Unix systems
to keep your credentials secure.
"""


def _normalize_domain_for_netrc(domain):
    """Normalize a domain-like input to a hostname suitable for .netrc lookup."""
    value = (domain or "").strip().lower()
    if not value:
        return ""

    # Support callers that accidentally pass full URLs.
    if "://" in value:
        parsed = urlparse(value)
        value = parsed.hostname or ""

    value = value.split("/", 1)[0]
    value = value.split(":", 1)[0]
    value = value.rstrip(".")
    return value


def _iter_netrc_domain_candidates(domain):
    """Yield hostname candidates from most specific to less specific."""
    normalized = _normalize_domain_for_netrc(domain)
    if not normalized:
        return

    parts = [part for part in normalized.split(".") if part]
    if len(parts) < 2:
        yield normalized
        return

    for i in range(0, len(parts) - 1):
        yield ".".join(parts[i:])


def _get_netrc_authenticators(netrc_obj, domain):
    """Find .netrc credentials, preferring the most specific domain match."""
    for candidate in _iter_netrc_domain_candidates(domain):
        creds = netrc_obj.authenticators(candidate)
        if creds is not None:
            return creds
    return None


def get_credentials(domain, args=None):
    """Get username and password from args, environment variables, or .netrc file.

    Checks for credentials in the following order:
    1. The ``args`` namespace (SPACEUSER and SPACEPSWD attributes)
    2. Environment variables ``SPACEUSER`` and ``SPACEPSWD``
    3. The ``~/.netrc`` file

    Args:
        domain: The domain name to look up credentials for.
        args: Optional argparse namespace with SPACEUSER and SPACEPSWD attributes.

    Returns:
        A tuple of (username, password). Either value may be None if not found.

    Examples:
        >>> import argparse
        >>> ns = argparse.Namespace(SPACEUSER="user1", SPACEPSWD="pass1")
        >>> get_credentials("example.com", args=ns)
        ('user1', 'pass1')

        When there aren't any environment variables or .netrc file, both username and password are None:
        >>> from unittest import mock
        >>> with mock.patch.dict(os.environ, clear=True):
        ...     get_credentials("example.com", args=None)
        (None, None)

    """
    username = None
    password = None

    # 1. Check args
    if args is not None:
        username = getattr(args, "SPACEUSER", None)
        password = getattr(args, "SPACEPSWD", None)

    # 2. Check environment variables
    if username is None:
        username = os.environ.get("SPACEUSER")
    if password is None:
        password = os.environ.get("SPACEPSWD")

    # 3. Check .netrc file (exact domain first, then progressively less specific domains)
    if username is None or password is None:
        try:
            netrc_obj = netrc.netrc()
            netrc_creds = _get_netrc_authenticators(netrc_obj, domain)
            if netrc_creds is not None:
                login, _, netrc_password = netrc_creds
                if username is None:
                    username = login
                if password is None:
                    password = netrc_password
        except (FileNotFoundError, netrc.NetrcParseError):
            pass

    return username, password
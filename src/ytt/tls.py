"""TLS setup for caption fetches.

The python.org macOS installer ships its own OpenSSL with an empty
certificate store until the user runs "Install Certificates.command". Every
HTTPS request then fails with CERTIFICATE_VERIFY_FAILED, and ytt silently
falls back to yt-dlp for each caption payload, which is many times slower.

When Python's own store is missing, use certifi if it is installed, otherwise
the system bundle macOS keeps at /etc/ssl/cert.pem. No new dependency.
"""

from __future__ import annotations

import os
import ssl
from functools import lru_cache
from typing import Callable, Iterable, Mapping, Optional

SYSTEM_BUNDLES = ("/etc/ssl/cert.pem", "/private/etc/ssl/cert.pem")


def _store_present(paths: ssl.DefaultVerifyPaths) -> bool:
    for f in (paths.cafile, paths.openssl_cafile):
        if f and os.path.isfile(f):
            return True
    for d in (paths.capath, paths.openssl_capath):
        if d and os.path.isdir(d) and os.listdir(d):
            return True
    return False


def _certifi_where() -> Optional[Callable[[], str]]:
    try:
        import certifi  # type: ignore
    except ImportError:
        return None
    return certifi.where


def fallback_ca_file(
    paths: ssl.DefaultVerifyPaths,
    env: Mapping[str, str],
    certifi_where: Optional[Callable[[], str]],
    system_bundles: Iterable[str],
) -> Optional[str]:
    """CA file to load instead of Python's default, or None to keep the default."""
    if env.get("SSL_CERT_FILE") or env.get("SSL_CERT_DIR"):
        return None  # the user chose a store explicitly
    if _store_present(paths):
        return None
    if certifi_where is not None:
        path = certifi_where()
        if path and os.path.isfile(path):
            return path
    for path in system_bundles:
        if os.path.isfile(path):
            return path
    return None


@lru_cache(maxsize=1)
def ssl_context() -> Optional[ssl.SSLContext]:
    """Context for urlopen, or None when Python's default store works."""
    cafile = fallback_ca_file(
        ssl.get_default_verify_paths(), os.environ, _certifi_where(), SYSTEM_BUNDLES
    )
    if cafile is None:
        return None
    return ssl.create_default_context(cafile=cafile)

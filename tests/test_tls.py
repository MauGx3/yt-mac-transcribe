"""CA bundle selection for caption fetches. No network."""
import os
import ssl
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ytt import tls  # noqa: E402


def paths(cafile=None, capath=None, openssl_cafile="/missing/cert.pem",
          openssl_capath="/missing/certs"):
    return ssl.DefaultVerifyPaths(cafile, capath, "SSL_CERT_FILE", openssl_cafile,
                                  "SSL_CERT_DIR", openssl_capath)


class TestFallbackCaFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bundle = os.path.join(self.tmp.name, "cert.pem")
        with open(self.bundle, "w") as fh:
            fh.write("pem")

    def test_working_python_store_needs_no_fallback(self):
        self.assertIsNone(tls.fallback_ca_file(paths(openssl_cafile=self.bundle), {},
                                               certifi_where=None, system_bundles=[]))

    def test_user_override_is_respected(self):
        self.assertIsNone(tls.fallback_ca_file(paths(), {"SSL_CERT_FILE": "/x.pem"},
                                               certifi_where=None, system_bundles=[self.bundle]))

    def test_missing_store_prefers_certifi(self):
        certifi = os.path.join(self.tmp.name, "certifi.pem")
        with open(certifi, "w") as fh:
            fh.write("pem")
        self.assertEqual(tls.fallback_ca_file(paths(), {}, certifi_where=lambda: certifi,
                                              system_bundles=[self.bundle]), certifi)

    def test_missing_store_uses_system_bundle_without_certifi(self):
        self.assertEqual(tls.fallback_ca_file(paths(), {}, certifi_where=None,
                                              system_bundles=["/missing.pem", self.bundle]),
                         self.bundle)

    def test_nothing_available_returns_none(self):
        self.assertIsNone(tls.fallback_ca_file(paths(), {}, certifi_where=None,
                                               system_bundles=["/missing.pem"]))


if __name__ == "__main__":
    unittest.main()

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.obsidian_bridge import build_output_path, is_allowed_origin, sanitize_component


class ObsidianBridgeTests(unittest.TestCase):
    def test_sanitize_component_strips_path_traversal_chars(self):
        self.assertEqual(
            sanitize_component("../../../.ssh/authorized_keys", "fallback"),
            "ssh_authorized_keys",
        )

    def test_sanitize_component_falls_back_when_empty(self):
        self.assertEqual(sanitize_component("...", "fallback"), "fallback")

    def test_build_output_path_stays_inside_target_dir(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = build_output_path(root, "../../../.ssh/authorized_keys", "")
            self.assertEqual(out.parent, root.resolve())
            self.assertEqual(out.name, "ssh_authorized_keys.txt")

    def test_allows_chrome_extension_origin_by_default(self):
        self.assertTrue(
            is_allowed_origin("chrome-extension://abcdefghijklmnop", [])
        )

    def test_rejects_web_origin_by_default(self):
        self.assertFalse(is_allowed_origin("https://evil.example", []))

    def test_explicit_origin_allowlist_still_works(self):
        self.assertTrue(
            is_allowed_origin(
                "chrome-extension://abcdefghijklmnop",
                ["chrome-extension://abcdefghijklmnop"],
            )
        )


if __name__ == "__main__":
    unittest.main()

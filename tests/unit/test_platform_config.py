import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from run_gateway import resolve_gateway_platform, validate_serial_port


class GatewayPlatformConfigTests(unittest.TestCase):
    def test_auto_resolves_windows_and_linux(self):
        self.assertEqual(
            resolve_gateway_platform("auto", system="win32"),
            "windows",
        )
        self.assertEqual(
            resolve_gateway_platform("auto", system="linux"),
            "linux",
        )

    def test_explicit_windows_and_linux_are_preserved(self):
        self.assertEqual(
            resolve_gateway_platform("windows", system="linux"),
            "windows",
        )
        self.assertEqual(
            resolve_gateway_platform("linux", system="win32"),
            "linux",
        )

    def test_com_port_is_windows_only(self):
        validate_serial_port("COM16", "windows")
        validate_serial_port(chr(92) * 2 + "." + chr(92) + "COM16", "windows")
        with self.assertRaisesRegex(
            ValueError,
            "SERIAL_PORT=COM16 incompatible avec GATEWAY_PLATFORM=linux",
        ):
            validate_serial_port("COM16", "linux")

    def test_linux_device_is_linux_only(self):
        validate_serial_port("/dev/ttyUSB0", "linux")
        with self.assertRaisesRegex(
            ValueError,
            "SERIAL_PORT=/dev/ttyUSB0 incompatible avec GATEWAY_PLATFORM=windows",
        ):
            validate_serial_port("/dev/ttyUSB0", "windows")

    def test_invalid_platform_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "GATEWAY_PLATFORM must be"):
            resolve_gateway_platform("macos", system="darwin")


if __name__ == "__main__":
    unittest.main()

"""Hardware selection and interrupted-restoration regressions; no live Hyprland."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("tablet_platform", Path(__file__).resolve().parents[1] / "platform.py")
platform = importlib.util.module_from_spec(spec)
spec.loader.exec_module(platform)


def monitor(name="eDP-1"):
    return dict(name=name, width=1920, height=1080, x=0, y=0,
                transform=0, refreshRate=60.0, scale=1.0)


class HardwareSelection(unittest.TestCase):
    def discover(self, devices, config=None, monitors=None):
        def hypr(command, **kwargs):
            return monitors if command == "monitors" else devices
        with patch.object(platform, "load_config", return_value=config or {}), \
             patch.object(platform, "hypr", side_effect=hypr):
            return platform.probe()

    def test_touch_only_hardware_is_supported(self):
        result = self.discover({"touch": [{"name": "vendor-finger"}]}, monitors=[monitor()])
        self.assertEqual(result["touch"]["name"], "vendor-finger")
        self.assertIsNone(result["pen"])
        self.assertIsNone(result["touchpad"])
        self.assertEqual(result["optional_devices"], {"pen": "absent", "touchpad": "absent"})

    def test_multiple_touchscreens_need_explicit_selection(self):
        devices = {"touch": [{"name": "screen-a"}, {"name": "screen-b"}]}
        with self.assertRaisesRegex(platform.PlatformError, "exactly one touchscreen"):
            self.discover(devices, monitors=[monitor()])
        selected = self.discover(devices, {"touchscreen": "screen-b"}, [monitor()])
        self.assertEqual(selected["touch"]["name"], "screen-b")

    def test_optional_null_leaves_ambiguous_devices_untouched(self):
        devices = {"touch": [{"name": "finger"}],
                   "tablets": [{"name": "pen-a"}, {"name": "pen-b"}],
                   "mice": [{"name": "a-touchpad"}, {"name": "b-touchpad"}]}
        with self.assertRaisesRegex(platform.PlatformError, "exactly one pen"):
            self.discover(devices, monitors=[monitor()])
        result = self.discover(devices, {"pen": None, "touchpad": None}, [monitor()])
        self.assertIsNone(result["pen"])
        self.assertIsNone(result["touchpad"])
        self.assertEqual(result["optional_devices"]["pen"], "disabled-by-config")

    def test_multiple_internal_monitors_need_explicit_selection(self):
        panels = [monitor("eDP-1"), monitor("DSI-1")]
        devices = {"touch": [{"name": "finger"}]}
        with self.assertRaisesRegex(platform.PlatformError, "exactly one active target monitor"):
            self.discover(devices, monitors=panels)
        result = self.discover(devices, {"monitor": "DSI-1"}, panels)
        self.assertEqual(result["monitor"]["name"], "DSI-1")

    def test_baseline_precedence_is_per_field(self):
        devices = {"touch": [{"name": "finger", "transform": 2}]}
        config = {"input_baseline": {"touchscreen": {"transform": 3, "output": "HDMI-A-1"}}}
        result = self.discover(devices, config, [monitor()])
        self.assertEqual(result["touch"]["transform"], 2)
        self.assertEqual(result["touch"]["output"], "HDMI-A-1")
        self.assertEqual(result["touch"]["field_sources"], {"transform": "runtime", "output": "config"})

    def test_config_rejects_duplicate_and_invalid_values(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            for content in ('{"pen":null,"pen":"other"}', '{"touchscreen":null}',
                            '{"input_baseline":{"touchscreen":{"transform":true}}}'):
                config_path.write_text(content)
                with patch.object(platform, "CONFIG_PATH", config_path), self.assertRaises(platform.PlatformError):
                    platform.load_config()


class RecoveryJournal(unittest.TestCase):
    def test_partial_restore_retains_journal_until_success(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal.json"
            baseline = {"monitor": {**monitor(), "mode": "1920x1080@60.00000"},
                        "touch": {"name": "finger", "transform": 0, "output": "eDP-1"},
                        "pen": None, "touchpad": None, "warnings": []}
            state = dict(version=1, session="isolated", phase="active", transform=1, baseline=baseline)
            platform.save_state(path, state)
            with patch.object(platform, "apply", side_effect=platform.PlatformError("device disconnected")):
                with self.assertRaisesRegex(platform.PlatformError, "restoration is incomplete"):
                    platform.restore(path, state)
            recovered = platform.load_state(path, "isolated")
            self.assertEqual(recovered["phase"], "restoring")
            self.assertEqual(recovered["baseline"]["touch"]["transform"], 0)
            with patch.object(platform, "apply"):
                platform.restore(path, recovered)
            self.assertFalse(path.exists())

    def test_malformed_journal_is_not_discarded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal.json"
            path.write_text('{"version":1,"session":"isolated","phase":"active"}')
            path.chmod(0o600)
            with self.assertRaisesRegex(platform.PlatformError, "refusing to discard"):
                platform.load_state(path, "isolated")
            self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()

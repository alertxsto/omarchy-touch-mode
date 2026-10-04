#!/usr/bin/env python3
"""Read-only diagnostics and explicitly requested, no-overwrite Lua generation."""

import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


# Load the sibling explicitly: importing "platform" could select Python's
# standard library module when this utility is called from another directory.
spec = importlib.util.spec_from_file_location("touch_mode_platform", Path(__file__).resolve().with_name("platform.py"))
platform = importlib.util.module_from_spec(spec)
spec.loader.exec_module(platform)


class SetupError(Exception):
    pass


def command(args):
    try:
        completed = subprocess.run(args, text=True, capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if completed.returncode:
        return False, completed.stderr.strip() or completed.stdout.strip() or f"Command exited with status {completed.returncode}"
    return True, completed.stdout.strip()


def sensor_status():
    if not shutil.which("gdbus"):
        return {"available": False, "error": "gdbus is missing (provided by glib2); SensorProxy cannot be inspected."}
    service = ["--system", "--dest", "net.hadess.SensorProxy", "--object-path", "/net/hadess/SensorProxy"]
    success, text = command(["gdbus", "introspect", *service, "--xml"])
    if not success:
        return {"available": False, "error": f"Cannot introspect SensorProxy: {text}"}
    try:
        node = ET.fromstring(text)
    except ET.ParseError as exc:
        return {"available": False, "error": f"SensorProxy introspection returned invalid XML: {exc}"}
    interface = next((item for item in node.findall("interface") if item.get("name") == "net.hadess.SensorProxy"), None)
    if interface is None:
        return {"available": False, "error": "The service does not expose net.hadess.SensorProxy."}
    methods = {item.get("name") for item in interface.findall("method")}
    properties = {item.get("name"): item.get("type") for item in interface.findall("property")}
    if not {"ClaimAccelerometer", "ReleaseAccelerometer"} <= methods or properties.get("HasAccelerometer") != "b" or properties.get("AccelerometerOrientation") != "s":
        return {"available": False, "error": "SensorProxy has an incompatible accelerometer interface."}
    success, text = command(["gdbus", "call", *service, "--method", "org.freedesktop.DBus.Properties.Get", "net.hadess.SensorProxy", "HasAccelerometer"])
    if not success:
        return {"available": False, "error": f"Cannot read SensorProxy HasAccelerometer: {text}"}
    match = re.fullmatch(r"\(<(true|false)>,\)", text)
    if match is None:
        return {"available": False, "error": f"Invalid SensorProxy HasAccelerometer response: {text}"}
    available = match.group(1) == "true"
    result = {"available": available, "interface": "net.hadess.SensorProxy", "claimTested": False}
    if not available:
        result["error"] = "SensorProxy reports no accelerometer. Keyboard and manual tablet rotation do not require one."
    else:
        result["note"] = "Read-only inspection; accelerometer claim permissions and physical calibration are not tested."
    return result


def doctor():
    commands = {name: shutil.which(name) for name in ("cc", "pkg-config", "wayland-scanner", "flock", "sha256sum", "hyprctl", "gdbus", "omarchy-shell")}
    commands["quickshell"] = shutil.which("qs") or shutil.which("quickshell")
    packages = {}
    for name in ("wayland-client", "xkbcommon", "gio-2.0"):
        if commands["pkg-config"]:
            available, detail = command(["pkg-config", "--modversion", name])
            packages[name] = {"available": available, "version" if available else "error": detail}
        else:
            packages[name] = {"available": False, "error": "pkg-config is missing."}
    try:
        monitors = platform.hypr("monitors", json_result=True)
        if not isinstance(monitors, list) or not monitors:
            raise platform.PlatformError("Hyprland returned no active monitor data.")
        hyprland = {"available": True, "monitorNames": [item.get("name") for item in monitors if isinstance(item, dict)]}
    except (platform.PlatformError, OSError, ValueError) as exc:
        hyprland = {"available": False, "error": str(exc)}
    missing = [name for name in ("cc", "pkg-config", "wayland-scanner", "flock", "sha256sum", "quickshell", "omarchy-shell") if not commands[name]]
    missing += [name for name in ("wayland-client", "xkbcommon") if not packages[name]["available"]]
    session = bool(os.environ.get("WAYLAND_DISPLAY") and os.environ.get("XDG_RUNTIME_DIR"))
    keyboard = {"available": not missing and session and hyprland["available"], "missingDependencies": missing,
                "waylandSession": session,
                "note": "Prerequisite availability only; this does not launch or type with the virtual keyboard. No touchscreen, pen, touchpad, or accelerometer is required."}
    try:
        hardware = platform.probe()
        tablet = {"available": True, "hardware": hardware,
                  "note": "Read-only probe; no display or input mutations and no physical calibration test."}
    except (platform.PlatformError, OSError, ValueError, KeyError, TypeError) as exc:
        tablet = {"available": False, "error": str(exc)}
    sensor = sensor_status()
    sensor_missing = [name for name in ("cc", "pkg-config", "flock", "sha256sum") if not commands[name]]
    if not packages["gio-2.0"]["available"]:
        sensor_missing.append("gio-2.0")
    sensor["missingDependencies"] = sensor_missing
    sensor["automaticRotationAvailable"] = sensor["available"] and not sensor_missing and tablet["available"]
    return {"commands": commands, "pkgConfig": packages, "hyprland": hyprland,
            "keyboard": keyboard, "tablet": tablet, "sensor": sensor}


def example_config():
    try:
        hardware = platform.probe()
    except (platform.PlatformError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Hardware detection unavailable; printing neutral example names: {exc}", file=sys.stderr)
        return {"monitor": "eDP-1", "touchscreen": "YOUR-TOUCHSCREEN-NAME", "pen": None, "touchpad": None,
                "input_baseline": {"touchscreen": {"transform": 0, "output": "eDP-1"},
                                   "pen": {"transform": 0, "output": "eDP-1"}}}
    baseline = {}
    for public, key in (("touchscreen", "touch"), ("pen", "pen")):
        device = hardware[key]
        baseline[public] = ({"transform": device["transform"], "output": device["output"]} if device is not None
                            else {"transform": 0, "output": hardware["monitor"]["name"]})
    return {"monitor": hardware["monitor"]["name"], "touchscreen": hardware["touch"]["name"],
            "pen": hardware["pen"]["name"] if hardware["pen"] is not None else None,
            "touchpad": hardware["touchpad"]["name"] if hardware["touchpad"] is not None else None,
            "input_baseline": baseline}


def write_touchscreen_config(destination):
    path = Path(destination).expanduser().absolute()
    # Fail before probing for an already-existing destination, including a
    # dangling symlink. The final hard link also refuses overwrite atomically.
    if path.name == "hyprland.lua":
        raise SetupError("Choose a separate Lua file; this utility never writes hyprland.lua.")
    if os.path.lexists(path):
        raise SetupError(f"Refusing to overwrite existing path: {path}")
    hardware = platform.probe()
    rows = ["-- Omarchy Touch Mode: explicitly generated input baseline.",
            "-- Load this file from your own hyprland.lua with dofile(...).",
            "-- Keep ~/.config/omarchy-tablet/config.json input_baseline in sync."]
    for key in ("touch", "pen"):
        device = hardware[key]
        if device is None:
            continue
        rows.append("hl.device({ " + ", ".join(f"{option} = {platform.lua(value)}" for option, value in
                    (("name", device["name"]), ("transform", device["transform"]), ("output", device["output"]))) + " })")
    data = "\n".join(rows) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=".touch-mode-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise SetupError(f"Refusing to overwrite existing path: {path}") from exc
    finally:
        os.unlink(temporary)
    print(f"Created {path}")
    print("No Hyprland configuration was modified or reloaded. To enable this file, add this line yourself to hyprland.lua:")
    print(f"dofile({platform.lua(str(path))})")
    print("Alternatively use require(\"module.name\") if you deliberately place the file on Lua's module search path; dofile with this absolute path is unambiguous.")
    print("Copy these actual baseline values into ~/.config/omarchy-tablet/config.json input_baseline if your Hyprland API cannot expose them:")
    print(json.dumps({"input_baseline": {public: {"transform": hardware[key]["transform"], "output": hardware[key]["output"]}
                                       for public, key in (("touchscreen", "touch"), ("pen", "pen")) if hardware[key] is not None}}, indent=2))
    for warning in hardware["warnings"]:
        print(f"Warning: {warning}", file=sys.stderr)


def main():
    arguments = sys.argv[1:]
    try:
        if arguments == ["doctor"]:
            result = doctor()
            print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
            # Hardware/sensor absence must not make a keyboard-only setup fail.
            return 0 if result["keyboard"]["available"] else 1
        if arguments == ["example-config"]:
            print(json.dumps(example_config(), ensure_ascii=False, allow_nan=False, indent=2))
            return 0
        if len(arguments) == 2 and arguments[0] == "write-touchscreen-config":
            write_touchscreen_config(arguments[1])
            return 0
        print("Usage: python3 setup.py doctor|example-config|write-touchscreen-config <path>", file=sys.stderr)
        return 2
    except (SetupError, platform.PlatformError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Touch Mode setup error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""One-shot tablet control; no config or stock toggle files are ever written.

Usage: python3 platform.py probe|begin|rotate <0|1|2|3>|end|status
The private journal survives shell/plugin reloads. Run end to recover an
interrupted action. When Hyprland omits per-device options, explicit user
input_baseline values take precedence over documented normal-transform /
target-monitor assumptions. The stock Omarchy persisted disable-name is
only a touchpad fallback, not proof of an arbitrary runtime override.
Every such fallback is exposed in the JSON warnings.
"""

import contextlib
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile


class PlatformError(Exception):
    pass


CONFIG_PATH = Path.home() / ".config/omarchy-tablet/config.json"
DEVICE_KEYS = {"touch": "touchscreen", "pen": "pen", "touchpad": "touchpad"}


def config_error(message):
    return PlatformError(f"Invalid configuration in {CONFIG_PATH}: {message}")


def load_config():
    try:
        with CONFIG_PATH.open(encoding="utf-8") as stream:
            config = json.load(stream, object_pairs_hook=unique_keys)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise config_error(str(exc)) from exc
    if not isinstance(config, dict):
        raise config_error("the root must be an object")
    unknown = config.keys() - {"monitor", "touchscreen", "pen", "touchpad", "input_baseline"}
    if unknown:
        raise config_error("unknown keys: " + ", ".join(sorted(unknown)))
    for key in ("monitor", "touchscreen", "pen", "touchpad"):
        if key not in config:
            continue
        value = config[key]
        if value is None and key in ("pen", "touchpad"):
            continue
        try:
            valid_name(value, key)
        except PlatformError as exc:
            raise config_error(f"{key} must be an exact device name" +
                               (" or null to disable it" if key in ("pen", "touchpad") else "")) from exc
    baseline = config.get("input_baseline", {})
    if not isinstance(baseline, dict) or baseline.keys() - {"touchscreen", "pen"}:
        raise config_error("input_baseline must be an object containing only touchscreen and/or pen")
    for kind, values in baseline.items():
        if not isinstance(values, dict) or values.keys() - {"transform", "output"}:
            raise config_error(f"input_baseline.{kind} must contain only transform and/or output")
        if "transform" in values:
            transform = values["transform"]
            if type(transform) is not int or transform not in range(-1, 8):
                raise config_error(f"input_baseline.{kind}.transform must be an integer from -1 to 7")
        if "output" in values:
            output = values["output"]
            if output != "":
                try:
                    valid_name(output, f"{kind} output")
                except PlatformError as exc:
                    raise config_error(f"input_baseline.{kind}.output must be a name or empty string") from exc
    return config


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key: {key}")
        result[key] = value
    return result


def hypr(*args, json_result=False):
    command = ["hyprctl"]
    if json_result:
        command.append("-j")
    command.extend(args)
    try:
        result = subprocess.run(command, text=True, capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PlatformError(f"Cannot communicate with Hyprland: {exc}") from exc
    text = result.stdout.strip()
    if result.returncode:
        raise PlatformError(result.stderr.strip() or text or "Hyprland command failed")
    if json_result:
        try:
            return json.loads(text)
        except ValueError as exc:
            raise PlatformError(f"Hyprland returned invalid JSON: {text}") from exc
    # hyprctl can report Lua/config errors with a successful process exit.
    if text != "ok":
        raise PlatformError(result.stderr.strip() or text or "Hyprland did not acknowledge the action")


def valid_name(value, label):
    if not isinstance(value, str) or not value or len(value) > 512:
        raise PlatformError(f"Invalid {label} name")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise PlatformError(f"Invalid control character in {label} name")
    return value


def lua(value):
    if isinstance(value, str):
        # JSON's Unicode escape syntax is NOT valid Lua. Keep UTF-8 characters
        # and encode control bytes using fixed-width Lua decimal escapes.
        return '"' + ''.join(
            '\\' + char if char in '\\"' else
            f"\\{ord(char):03d}" if ord(char) < 32 or ord(char) == 127 else char
            for char in value
        ) + '"'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and math.isfinite(value):
        return str(value)
    raise PlatformError("Cannot serialize an invalid Lua option")


def apply(kind, options):
    if kind not in ("monitor", "device"):
        raise PlatformError("Invalid Hyprland action")
    name_key = "output" if kind == "monitor" else "name"
    valid_name(options[name_key], kind)
    table = ", ".join(f"{key} = {lua(value)}" for key, value in options.items())
    hypr("eval", f"hl.{kind}({{ {table} }})")


def number(value, label, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise PlatformError(f"Invalid {label} reported by Hyprland")
    if integer and value != int(value):
        raise PlatformError(f"Invalid {label} reported by Hyprland")
    return int(value) if integer else value


def monitor_snapshot(monitor):
    result = {"name": valid_name(monitor.get("name"), "monitor")}
    for key in ("width", "height", "x", "y", "transform", "refreshRate", "scale"):
        result[key] = number(monitor.get(key), key, key not in ("refreshRate", "scale"))
    if result["width"] <= 0 or result["height"] <= 0 or result["scale"] <= 0 or result["refreshRate"] <= 0:
        raise PlatformError("The internal panel has no usable display mode")
    if result["transform"] not in range(8):
        raise PlatformError("The internal panel has an invalid transform")
    # monitors JSON width/height are the physical pixel mode, not the rotated
    # logical dimensions. Never swap them for portrait orientations.
    result["mode"] = f'{result["width"]}x{result["height"]}@{result["refreshRate"]:.5f}'
    return result


def select_device(devices, group, kind, config):
    key = DEVICE_KEYS[kind]
    if key in config and config[key] is None:
        return None
    choices = devices.get(group, [])
    if not isinstance(choices, list) or any(not isinstance(entry, dict) for entry in choices):
        raise PlatformError(f"Hyprland returned an invalid {key} device list")
    if key in config:
        matches = [entry for entry in choices if entry.get("name") == config[key]]
        source = "config"
    else:
        matches = [entry for entry in choices if kind != "touchpad" or
                   "touchpad" in str(entry.get("name", "")).lower() or
                   entry.get("type") == "touchpad"]
        source = "auto"
    if not matches and kind != "touch" and key not in config:
        return None
    if len(matches) != 1:
        names = ", ".join(repr(entry.get("name")) for entry in matches) or "none"
        optional = "; set it to null to leave this optional device untouched" if kind != "touch" else ""
        raise PlatformError(f"Cannot identify exactly one {key} (candidates: {names}). "
                            f'Set "{key}" to its exact Hyprland name in {CONFIG_PATH}{optional}.')
    valid_name(matches[0].get("name"), key)
    return {**matches[0], "selection_source": source}


def input_snapshot(device, panel, kind, warnings, config):
    if device is None:
        return None
    key = DEVICE_KEYS[kind]
    configured = config.get("input_baseline", {}).get(key, {})
    result = {"name": device["name"], "selection_source": device["selection_source"]}
    sources = {}
    for field, default in (("transform", 0), ("output", panel)):
        if field in device:
            value, source = device[field], "runtime"
        elif field in configured:
            value, source = configured[field], "config"
        else:
            value, source = default, "assumed-normal-baseline"
        if field == "transform":
            value = number(value, f"{key} transform", True)
            if value not in range(-1, 8):
                raise PlatformError(f"Invalid {key} transform")
        elif value != "":
            valid_name(value, f"{key} output")
        result[field] = value
        sources[field] = source
        if source != "runtime":
            warnings.append(f"{key.capitalize()} {field} is not exposed by this Hyprland API; "
                            f"restoration uses {source} value {value!r}. "
                            f"Set input_baseline.{key}.{field} in {CONFIG_PATH} to your actual baseline; "
                            "unpersisted runtime overrides cannot be captured.")
    result["field_sources"] = sources
    result["source"] = next(iter(set(sources.values()))) if len(set(sources.values())) == 1 else "mixed"
    return result


def probe():
    config = load_config()
    monitors = hypr("monitors", json_result=True)
    devices = hypr("devices", json_result=True)
    if not isinstance(monitors, list) or any(not isinstance(m, dict) for m in monitors) or not isinstance(devices, dict):
        raise PlatformError("Hyprland returned invalid monitor or device data")
    active = [m for m in monitors if not m.get("disabled", False)]
    if "monitor" in config:
        panels = [m for m in active if m.get("name") == config["monitor"]]
        source = "config"
    else:
        panels = [m for m in active if isinstance(m.get("name"), str) and m["name"].startswith(("eDP-", "LVDS-", "DSI-"))]
        source = "auto"
    if len(panels) != 1:
        names = ", ".join(repr(m.get("name")) for m in panels) or "none"
        raise PlatformError(f"Cannot identify exactly one active target monitor (candidates: {names}). "
                            f'Set "monitor" to its exact Hyprland name in {CONFIG_PATH}.')
    panel = monitor_snapshot(panels[0])
    panel["selection_source"] = source
    warnings = []
    touch = input_snapshot(select_device(devices, "touch", "touch", config), panel["name"], "touch", warnings, config)
    pen = input_snapshot(select_device(devices, "tablets", "pen", config), panel["name"], "pen", warnings, config)
    pad = select_device(devices, "mice", "touchpad", config)
    touchpad = None
    if pad is not None:
        touchpad = {"name": pad["name"], "selection_source": pad["selection_source"]}
        if isinstance(pad.get("enabled"), bool):
            touchpad.update(enabled=pad["enabled"], source="runtime")
        else:
            # Stock toggle uses this exact path regardless of XDG_STATE_HOME.
            persisted = Path.home() / ".local/state/omarchy/toggles/hypr/touchpad-disabled-name"
            try:
                with persisted.open(encoding="utf-8") as stream:
                    disabled_name = stream.readline(1024).rstrip("\n")
            except FileNotFoundError:
                disabled_name = None
            touchpad.update(enabled=disabled_name != pad["name"], source="omarchy-persisted-toggle-fallback")
            warnings.append("Touchpad enabled state is inferred from the stock Omarchy disabled-name file; unpersisted runtime enabled overrides cannot be read by this Hyprland API.")
    return {"monitor": panel, "touch": touch, "pen": pen, "touchpad": touchpad, "warnings": warnings,
            "configFile": str(CONFIG_PATH), "optional_devices": {
                key: ("disabled-by-config" if key in config and config[key] is None else
                      "selected" if value is not None else "absent")
                for key, value in (("pen", pen), ("touchpad", touchpad))}}


def state_paths():
    session = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if not session:
        raise PlatformError("HYPRLAND_INSTANCE_SIGNATURE is not set")
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    info = runtime.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise PlatformError("The user runtime directory is not private")
    directory = runtime / "omarkyy.tablet"
    token = hashlib.sha256(session.encode()).hexdigest()[:24]
    return directory, directory / f"{token}.json", directory / f"{token}.lock", session


@contextlib.contextmanager
def state_lock(directory, lockfile):
    directory.mkdir(mode=0o700, exist_ok=True)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise PlatformError("Tablet runtime state directory is not private")
    fd = os.open(lockfile, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise PlatformError("Tablet runtime lock is not private")
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def load_state(path, session):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, encoding="utf-8") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise PlatformError("Tablet recovery state is not private")
        try:
            state = json.load(stream, object_pairs_hook=unique_keys)
        except ValueError as exc:
            raise PlatformError("Tablet recovery state is invalid; refusing to discard it") from exc
    try:
        if not isinstance(state, dict) or state.get("version") != 1 or state.get("session") != session:
            raise ValueError("unsupported journal version or session")
        if state.get("phase") not in ("beginning", "active", "rotating", "restoring"):
            raise ValueError("invalid journal phase")
        if type(state.get("transform")) is not int or state["transform"] not in range(8):
            raise ValueError("invalid journal transform")
        baseline = state["baseline"]
        if not isinstance(baseline, dict):
            raise ValueError("invalid journal baseline")
        if not isinstance(baseline["monitor"], dict):
            raise ValueError("invalid journal monitor")
        monitor_snapshot(baseline["monitor"])
        valid_name(baseline["monitor"]["mode"], "monitor mode")
        if not isinstance(baseline["warnings"], list) or any(not isinstance(w, str) for w in baseline["warnings"]):
            raise ValueError("invalid journal warnings")
        for kind in ("touch", "pen"):
            device = baseline[kind]
            if device is None and kind == "pen":
                continue
            valid_name(device["name"], kind)
            if type(device["transform"]) is not int or device["transform"] not in range(-1, 8):
                raise ValueError("invalid journal input transform")
            if device["output"] != "":
                valid_name(device["output"], f"{kind} output")
        pad = baseline["touchpad"]
        if pad is not None:
            valid_name(pad["name"], "touchpad")
            if not isinstance(pad["enabled"], bool):
                raise ValueError("invalid journal touchpad baseline")
    except (PlatformError, ValueError, KeyError, TypeError) as exc:
        raise PlatformError(f"Tablet recovery state is invalid; refusing to discard it: {exc}") from exc
    return state


def save_state(path, state):
    fd, temporary = tempfile.mkstemp(prefix=".tablet-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def monitor_options(baseline, transform):
    panel = baseline["monitor"]
    return {"output": panel["name"], "mode": panel["mode"], "position": f'{panel["x"]}x{panel["y"]}', "scale": panel["scale"], "transform": transform}


def restore(path, state):
    state["phase"] = "restoring"
    save_state(path, state)
    baseline = state["baseline"]
    actions = [("monitor", monitor_options(baseline, baseline["monitor"]["transform"]))]
    for kind in ("touch", "pen"):
        device = baseline.get(kind)
        if device is not None:
            actions.append(("device", {"name": device["name"], "transform": device["transform"], "output": device["output"]}))
    pad = baseline.get("touchpad")
    if pad is not None:
        actions.append(("device", {"name": pad["name"], "enabled": pad["enabled"]}))
    errors = []
    # Independent requests ensure a panel failure never prevents re-enabling
    # the touchpad. Keep the journal until every restoration is acknowledged.
    for kind, options in actions:
        try:
            apply(kind, options)
        except PlatformError as exc:
            errors.append(str(exc))
    if errors:
        raise PlatformError("Desktop restoration is incomplete; run end again: " + "; ".join(errors))
    path.unlink()


def result(state, path):
    if state is None:
        return {"active": False, "phase": "inactive", "stateFile": str(path)}
    baseline = state["baseline"]
    return {"active": True, "phase": state["phase"], "monitor": baseline["monitor"]["name"], "transform": state["transform"], "stateFile": str(path), "warnings": baseline["warnings"]}


def run(action, transform=None):
    if action == "probe":
        return probe()
    directory, path, lockfile, session = state_paths()
    with state_lock(directory, lockfile):
        state = load_state(path, session)
        if action == "status":
            return result(state, path)
        if action == "end":
            if state:
                restore(path, state)
            return result(None, path)
        if action == "begin":
            if state:
                if state["phase"] != "active":
                    raise PlatformError("An interrupted tablet action needs recovery; run end before begin")
                return result(state, path)
            baseline = probe()
            state = {"version": 1, "session": session, "baseline": baseline, "transform": baseline["monitor"]["transform"], "phase": "beginning"}
            save_state(path, state)
            try:
                if baseline.get("touchpad") is not None:
                    apply("device", {"name": baseline["touchpad"]["name"], "enabled": False})
                state["phase"] = "active"
                save_state(path, state)
            except (PlatformError, OSError) as exc:
                try:
                    restore(path, state)
                except (PlatformError, OSError) as recovery:
                    raise PlatformError(f"Cannot begin tablet mode: {exc}; {recovery}") from exc
                raise PlatformError(f"Cannot begin tablet mode; desktop baseline restored: {exc}") from exc
            return result(state, path)
        if not state or state["phase"] != "active":
            raise PlatformError("Tablet mode is not active; run begin first (or end to recover an interrupted action)")
        baseline = state["baseline"]
        state["phase"] = "rotating"
        save_state(path, state)
        try:
            apply("monitor", monitor_options(baseline, transform))
            for kind in ("touch", "pen"):
                device = baseline.get(kind)
                if device is not None:
                    apply("device", {"name": device["name"], "transform": transform, "output": baseline["monitor"]["name"]})
            # Reassert the runtime-only tablet state after a Hyprland reload.
            if baseline.get("touchpad") is not None:
                apply("device", {"name": baseline["touchpad"]["name"], "enabled": False})
            state.update(transform=transform, phase="active")
            save_state(path, state)
        except (PlatformError, OSError) as exc:
            try:
                restore(path, state)
            except (PlatformError, OSError) as recovery:
                raise PlatformError(f"Cannot rotate the internal panel: {exc}; {recovery}") from exc
            raise PlatformError(f"Cannot rotate the internal panel; desktop baseline restored: {exc}") from exc
        return result(state, path)


def main():
    arguments = sys.argv[1:]
    if len(arguments) == 1 and arguments[0] in ("probe", "begin", "end", "status"):
        action, transform = arguments[0], None
    elif len(arguments) == 2 and arguments[0] == "rotate" and arguments[1] in ("0", "1", "2", "3"):
        action, transform = "rotate", int(arguments[1])
    else:
        print("Usage: platform.py probe|begin|rotate <0|1|2|3>|end|status", file=sys.stderr)
        return 2
    try:
        payload = run(action, transform)
        print(json.dumps({"ok": True, **payload}, ensure_ascii=False, allow_nan=False))
        return 0
    except (PlatformError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Tablet platform error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

# Installation and lifecycle

[README](../README.md) · [Configuration](configuration.md) · [Troubleshooting](troubleshooting.md)

## 1. Confirm the desktop contract

OMARCHY TOUCH MODE is a plugin for **Omarchy Quattro's Quickshell shell**, not the older Waybar desktop. The target installation uses **Quickshell 0.3.1** and **Lua-based Hyprland** runtime operations. Running a second independent Quickshell instance is neither required nor the normal install procedure.

You need a running Wayland/Hyprland session with `omarchy`, `omarchy-shell`, and `hyprctl` available. A working keyboard also needs the compositor's Wayland virtual-keyboard protocol. Sensor hardware is **not** needed for the keyboard.

For tablet mode, automatic discovery requires exactly one active internal `eDP-`, `LVDS-`, or `DSI-` panel and one touchscreen. A pen and touchpad are optional. Multiple candidates require [explicit device configuration](configuration.md); auto-selection never chooses the first candidate arbitrarily. Auto-rotation additionally needs an accelerometer supported by SensorProxy.

## 2. Install dependencies explicitly

Run the following yourself, before adding the plugin:

```sh
sudo pacman -S --needed base-devel wayland wayland-protocols libxkbcommon glib2 python iio-sensor-proxy util-linux coreutils
```

| Package | Purpose |
| --- | --- |
| `base-devel` | C compiler and build tooling, including `pkg-config` support |
| `wayland` | Wayland client library and `wayland-scanner` |
| `wayland-protocols` | Wayland protocol development resources |
| `libxkbcommon` | Stable US/evdev keyboard keymap |
| `glib2` | GLib/GIO, system D-Bus access and event-driven sensor helper |
| `python` | Hardware selection, one-shot Hyprland actions, recovery, setup diagnostics |
| `iio-sensor-proxy` | Exposes supported accelerometers through SensorProxy |
| `util-linux` | `flock` for serialized native-helper builds (normally already installed by Omarchy) |
| `coreutils` | `sha256sum` for source-content cache keys (normally already installed by Omarchy) |

The keyboard does not need an available SensorProxy service or accelerometer. The full dependency command includes sensor support so supported laptops can use both features. Installing a package cannot add an accelerometer or a missing kernel driver.

If SensorProxy is installed but unavailable, investigate its service as described in [troubleshooting](troubleshooting.md#sensor-orientation-does-not-arrive). The plugin does not start privileged services or change their enablement.

## 3. Review, install, and enable

Review [the repository](https://github.com/alertxsto/omarchy-touch-mode) and its native/Python helpers. Omarchy plugins run **unsandboxed** with your user account's access. The normal plugin installer displays a trust warning. Manifest validation and a marketplace listing are not security audits.

```sh
omarchy plugin add https://github.com/alertxsto/omarchy-touch-mode --enable
```

For an existing installation:

```sh
omarchy plugin enable omarkyy.tablet
omarchy plugin list
```

The ID stays `omarkyy.tablet` despite the public project/repository name. The normal installed source directory is:

```text
~/.config/omarchy/plugins/omarkyy.tablet/
```

Omarchy clones the repository, validates the root manifest, and enables it through its plugin system. **It never runs a plugin install hook.** OMARCHY TOUCH MODE therefore does not depend on an install script having run. It does not install packages, invoke `sudo`, or edit `~/.config/hypr`.

Native helper paths are resolved relative to the plugin's QML/source directory. The default installed path in these examples is a convenience for terminal commands, not a hardcoded runtime requirement. For a development checkout or a customized installation path, run the same Python scripts from that source directory instead.

## 4. Readiness and first use

From the installed source directory:

```sh
cd "$HOME/.config/omarchy/plugins/omarkyy.tablet"
python3 setup.py doctor
```

`doctor` emits a JSON report with separate keyboard, tablet, and sensor diagnostics. It inspects readiness without entering tablet mode, disabling input devices, or changing monitor transforms. A tablet/sensor failure does not by itself mean that the keyboard is unusable. Read any restoration-baseline warnings even when device selection succeeds.

Open the keyboard:

```sh
omarchy-shell omarkyy.tablet keyboard
```

Click/tap an application's text field, then type. The keyboard does not take keyboard focus. Try a short harmless text string before testing shortcuts.

### First-use compilation

The `.sh` wrappers compile the C helpers when the source-content hash changes or a cached binary is absent. Compilation happens under your user account and requires no `sudo`; a file lock serializes concurrent builds.

- Both native helpers use `${XDG_CACHE_HOME:-$HOME/.cache}/omarchy/tablet/`, with source-hash cache entries and private creation permissions.
- Wayland scanner output and native binaries stay in the cache, outside the plugin's watched source directory.
- The helper becomes one native process after the wrapper `exec`s it; typing does not spawn a compiler or a process per key.

Initial keyboard startup may show “Preparing keyboard…”. A build failure appears in the keyboard header or shell process diagnostics. Install the missing dependency instead of changing compiler flags to hide the error.

### First tablet session

Save work first, keep a physical keyboard or terminal available, and read the [restoration baseline explanation](configuration.md#restoration-baselines). Enter explicitly:

```sh
omarchy-shell omarkyy.tablet tablet
omarchy-shell omarkyy.tablet status
```

The keyboard opens automatically, the selected touchpad is disabled if present, and unlocked rotation starts sensor listening. Use the header's Tablet and Rotation controls when working entirely by touch. There is no hinge detector: folding the laptop does not enter tablet mode automatically.

Test touch alignment on your own machine before relying on tablet mode. Rotation values accepted by the compositor are not proof of correct physical sensor orientation or pen calibration.

Exit:

```sh
omarchy-shell omarkyy.tablet off
omarchy-shell omarkyy.tablet status
```

Wait for `busy` to become false and confirm `tabletMode` is false. An error must be resolved before proceeding with an update/removal. IPC operations are asynchronous; a successful command dispatch is not proof that restoration has completed.

## Update

Exit tablet mode first, then review the update:

```sh
omarchy-shell omarkyy.tablet off
omarchy-shell omarkyy.tablet status
omarchy plugin update omarkyy.tablet
```

Omarchy's updater fast-forwards the git-managed checkout and validates the new revision; local modifications may prevent an update. Keep laptop overrides in `~/.config/omarchy-tablet/config.json`, not edits to plugin source. Omarchy watches plugin sources and may reload after changes; do not update during a tablet transition.

The changed helpers rebuild on their next use. Read release/commit documentation for any changed configuration or baseline behavior. Do not infer physical calibration coverage from a successful source update.

## Disable and remove safely

Before disabling or removing, exit tablet mode and check completion:

```sh
omarchy-shell omarkyy.tablet off
omarchy-shell omarkyy.tablet status
```

Then choose one:

```sh
omarchy plugin disable omarkyy.tablet
```

```sh
omarchy plugin remove omarkyy.tablet
```

Normal component destruction attempts recovery, but it cannot guarantee success after a shell crash or unavailable compositor. Do not rely on removal to repair a failed transition.

If IPC is unavailable, restore **while the source still exists**, in the same active Hyprland session:

```sh
python3 "$HOME/.config/omarchy/plugins/omarkyy.tablet/platform.py" end
```

The plugin intentionally does not delete:

- Your `~/.config/omarchy-tablet/config.json` overrides.
- Any optional Lua mapping file you explicitly generated and loaded.
- Native build cache files.

These are user-owned. An optional mapping remains active independently if your Hyprland configuration still loads it; remove the corresponding manual `require`/`dofile` reference yourself if you no longer want that baseline. Review files before removing them. Never discard an active recovery journal instead of restoring the desktop.

## Official references

- [Omarchy plugin user guide](https://github.com/omacom/omarchy/blob/quattro/manual/32-shell-plugins.md)
- [Quattro shell reference](https://github.com/omacom/omarchy/blob/quattro/docs/omarchy-shell.md)
- [Marketplace development guide](https://plugins.omarchy.org/develop.html)

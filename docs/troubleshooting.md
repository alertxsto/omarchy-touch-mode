# Troubleshooting and recovery

[README](../README.md) · [Install](install.md) · [Configuration](configuration.md)

## Start with safe diagnostics

Run commands in the active desktop session, not through a root shell, a different login, or an unrelated SSH environment. Use the installed source directory, or substitute the real path of your checkout:

```sh
cd "$HOME/.config/omarchy/plugins/omarkyy.tablet"
python3 setup.py doctor
omarchy plugin list
omarchy-shell omarkyy.tablet status
python3 platform.py status
```

These report different things:

- `doctor`: command/pkg-config availability, Hyprland hardware selection, and SensorProxy availability. Keyboard/tablet/sensor readiness are separate.
- Shell `status`: QML service state (`tabletMode`, `rotationLocked`, `orientation`, `busy`, `error`).
- Platform `status`: private journal state, including whether restoration is still needed and the journal location.

`doctor` is read-only: it does not type, claim the sensor, rotate the display, disable the touchpad, reload configuration, or install anything. Its successful exit is tied to keyboard prerequisites, **not proof that tablet hardware or physical touch calibration works**. Inspect the tablet/sensor sections even when its exit code is zero. Likewise, command availability is not proof that the compositor exposes the virtual-keyboard protocol.

A shell state of `tabletMode: false` does not prove that no recovery journal exists after a failed operation. Use platform status when investigating interrupted actions.

## Desktop stuck after a tablet action

First attempt normal exit:

```sh
omarchy-shell omarkyy.tablet off
omarchy-shell omarkyy.tablet status
```

Wait for `busy: false`. `off` tries restoration even when the service believes tablet mode is already inactive. If IPC is unavailable or an error remains:

```sh
python3 "$HOME/.config/omarchy/plugins/omarkyy.tablet/platform.py" end
```

Run it while the same Hyprland session is still live. Recovery uses the captured journal rather than probing a new baseline. It attempts monitor and device restores independently, so a monitor failure does not skip touchpad restoration. It deletes the journal only after all required restores are acknowledged.

If restoration is incomplete, resolve the specific error and run `end` again. A disconnected display/device may need to be made available. If Hyprland is not responding, repair the session connection first. Do not remove the plugin source, delete the journal, replace it with guessed JSON, or reboot merely to hide a reported restoration failure.

The service also attempts `end` on startup to recover its own previous journal. Without a journal, this makes no monitor/device changes. Component destruction attempts restoration when tablet mode is active, but abrupt process death cannot guarantee that callback runs.

### Privacy/invalid-journal errors

The runtime directory and journal must belong to your user and remain private. Journals are associated with the Hyprland instance signature and use a versioned schema. Unsafe file permissions, malformed state, or an unsupported journal are explicit errors; the plugin refuses to silently discard captured state.

Inspect the reported `stateFile` and ownership without sharing its contents publicly. Do not run the helper with `sudo`, broaden runtime permissions, or repoint session environment variables at another user's/session's journal. An old valid version-1 journal from the installed implementation remains supported, including its device baselines; new journals can represent optional devices as absent.

## Plugin or bar icon missing

```sh
omarchy plugin list
omarchy plugin enable omarkyy.tablet
omarchy plugin validate "$HOME/.config/omarchy/plugins/omarkyy.tablet"
```

Confirm that you are using Quattro's plugin shell, not a classic Waybar setup. Manifest validation checks layout/schema, not runtime compositor compatibility or physical device behavior. Review the shell's live diagnostics for missing imports or QML errors.

The widget is designed for the Quattro bar contract. A third-party replacement bar can have different service-access behavior; test with the built-in Omarchy bar before treating that as a hardware error. The plugin does not hide the bar in tablet mode.

If the installed source directory differs, pass its actual location to validation. Do not create a second independent Quickshell instance as an attempted fix.

## Keyboard remains on “Preparing keyboard…”

Check that dependencies were explicitly installed:

```sh
command -v cc pkg-config wayland-scanner python3 flock sha256sum
pkg-config --modversion wayland-client xkbcommon gio-2.0
```

If any are missing, install the [documented packages](install.md#2-install-dependencies-explicitly). The installer never runs build/install hooks. First use compiles into `${XDG_CACHE_HOME:-$HOME/.cache}/omarchy/tablet/`; the cache must be writable by your user. Builds are locked and keyed by source content.

Read the keyboard header error and the shell's stderr, rather than waiting indefinitely. For direct helper diagnostics, **close the visible keyboard first**, then run:

```sh
cd "$HOME/.config/omarchy/plugins/omarkyy.tablet"
sh input-backend.sh
```

This builds if required and starts the native input helper. It should print `ready` only after establishing the Wayland keyboard. Do not paste key commands into its stdin unless you intend to inject input into the focused application. Press Ctrl+C to stop this diagnostic process. A terminal `ready` does not test touch interaction or every shortcut.

Do not disable `-Werror` to hide compiler output. Include the actual diagnostic in a bug report. Avoid indiscriminately deleting caches while a build/helper is running.

## Virtual-keyboard protocol or Wayland error

Errors such as “Cannot connect to Wayland display” indicate that the helper cannot reach the active Wayland session. Run as your normal desktop user, with that session's environment:

```sh
printenv WAYLAND_DISPLAY HYPRLAND_INSTANCE_SIGNATURE XDG_RUNTIME_DIR
```

Do not invent/export guessed socket names or use `sudo`. “Compositor does not expose the virtual-keyboard protocol” means the required `zwp_virtual_keyboard_manager_v1` interface was not available. This cannot be fixed by installing `ydotool`, enabling `uinput`, or granting root permissions: those are not this plugin's input path. Confirm the supported compositor/runtime contract.

A missing/unsupported sensor does not affect this Wayland input path; investigate keyboard errors separately.

## Typing goes nowhere, to the wrong window, or repeats unexpectedly

The keyboard is a non-focusable layer surface. It deliberately leaves keyboard focus with your application.

1. Click/tap the target application's editable field before using the keyboard.
2. Check that the application still has focus, especially after a workspace shortcut.
3. Check whether Ctrl/Super/Alt/Shift or Caps is latched in the keyboard UI.
4. Release the held key; workspace or active-window changes also stop repeat.
5. Close/reopen the keyboard to reset its modifier state and restart its helper.

Only Backspace, Delete, and arrows hold-repeat: 350 ms initial delay, then 45 ms. Modifiers last for one complete held sequence; Caps is persistent until toggled or reset. A desktop shortcut such as Super+1 intentionally changes the target workspace, so do not interpret subsequent typing elsewhere as keyboard focus theft.

The plugin does not reserve desktop area or apply a full-screen input grab. Small screens constrain keyboard dimensions; drag the header or resize handle to reach obscured content.

In the pointer-driven release smoke, a single-line GTK Entry replaced earlier characters while GTK TextView accumulated text correctly. This is an observed application-specific limitation, not an established root cause or a claim that all GTK applications fail. If you encounter replacement, check selected text and report the exact application, widget, and pointer/touch sequence.

## Keyboard/keymap mismatch

This keyboard is **US**, using a stable `evdev`/`pc105` US keymap and real keycodes. It is not dynamically synchronized to another physical keyboard's layout, an application input method, or a desktop layout-switcher plugin. Labels for letter keys are uppercase; actual output follows Shift/Caps state.

If a shortcut fails, test ordinary typing and Shift first, then a harmless application shortcut. Application interception and compositor bindings are separate from text insertion. Provide the exact key sequence, modifier state, focused application, and physical-keyboard layout when reporting a mismatch. Do not fix it by substituting a transient keymap per keystroke; stable keycodes are essential to compositor shortcut behavior.

## Hardware selection is ambiguous or missing

```sh
hyprctl -j monitors
hyprctl -j devices
python3 "$HOME/.config/omarchy/plugins/omarkyy.tablet/platform.py" probe
```

The error lists candidates. Add the exact `monitor`, `touchscreen`, `pen`, or `touchpad` name to `~/.config/omarchy-tablet/config.json` as appropriate. Omit a key for autodetection; use `null` only for optional pen/touchpad exclusion. `false` and unknown/duplicate keys are invalid.

No pen or touchpad is valid and should not stop tablet mode. No touchscreen prevents tablet mode, but not the standalone keyboard. Multiple tablet/pen candidates may include external drawing tablets; choose deliberately or exclude pen handling. Automatic touchpad selection filters mouse entries by touchpad identity; a normal USB mouse is not a fallback touchpad.

Exit tablet mode before changing overrides. Do not rename a physical device or modify system udev rules merely to match another laptop's example. See the [complete schema](configuration.md#user-owned-configuration-file).

## Sensor orientation does not arrive

Read the independent sensor section in `doctor`. Then use the helper's non-claiming probe:

```sh
cd "$HOME/.config/omarchy/plugins/omarkyy.tablet"
sh sensor-backend.sh --probe
```

For service diagnostics:

```sh
systemctl status iio-sensor-proxy.service
journalctl -u iio-sensor-proxy.service -b --no-pager
```

If appropriate on your system, start the installed service yourself:

```sh
sudo systemctl start iio-sensor-proxy.service
```

That is an explicit administrator action, not something the plugin does. Starting the service does not ensure a sensor is supported. SensorProxy must expose `net.hadess.SensorProxy` on the **system bus**, report `HasAccelerometer: true`, and permit `ClaimAccelerometer`. An absent sensor, D-Bus access denial, malformed property, service disappearance, or replacement is reported instead of simulated data.

`undefined` means no usable orientation has been determined; it is not a fifth rotation. Real events use `normal`, `left-up`, `bottom-up`, or `right-up`.

The watcher runs only while tablet mode is active and rotation unlocked. Rotation lock releases the claim. A failed watcher locks rotation and shows an error; the keyboard remains independent. Resolve the cause, then explicitly unlock to try again.

For an event-stream diagnostic, exit tablet mode first so there is not another plugin watcher, then:

```sh
sh sensor-backend.sh --watch
```

This **does claim the accelerometer** until stopped. Rotate the actual laptop and observe events; stop with Ctrl+C. It does not itself rotate the monitor. A driver reporting only one orientation needs sensor/driver investigation, not a fabricated event stream or constant polling.

## Display rotates but touch/pen is offset

Exit tablet mode safely. Inspect the actual display and device names, existing Lua device mapping, and probe warnings. Set explicit restoration baseline fields where runtime options are unreadable. The plugin cannot infer an arbitrary existing mapping absent from the API.

Test the real machine in each orientation: tap corners/edges, drag across the screen, and test pen position separately if present. Correct transform command output is **not** physical calibration proof. A sensor mounting mismatch, touchscreen coordinate transform, and pen calibration are different problems. Provide which orientation and which device fails; avoid changing unrelated monitor scale or input baseline until the mismatch is understood.

Do not reload Hyprland while tablet mode is active. Configuration reloads can replace temporary runtime options, and another config block can override generated mappings. The optional generator writes a separate file only; a mapping is not persistent until you deliberately load it.

## Optional Lua generator refuses a destination

This is expected when the file already exists, is a symlink, is named `hyprland.lua`, or its parent does not exist. Choose a separate new output path with an existing parent. The generator is intentionally no-overwrite and will not create or replace your main Hyprland configuration. Review [manual mapping instructions](configuration.md#optional-persistent-lua-touchscreen-mapping).

## Logs and useful bug reports

Header errors are short and may be elided. Capture the full helper stderr or the diagnostics from the way your Omarchy shell is actually launched. There is **no plugin-specific persistent log file or guaranteed shell journal unit name**. Use your real shell process/service logs; do not assume a made-up `omarchy-tablet.log` path exists.

Open issues at [alertxsto/omarchy-touch-mode](https://github.com/alertxsto/omarchy-touch-mode/issues), with:

- Omarchy/Hyprland/Quickshell versions and whether the built-in bar is used.
- Installed plugin revision/version and dependency/build diagnostics.
- Exact action sequence and whether keyboard-only use works.
- `doctor`, shell status, and platform status outputs, sanitized.
- Relevant selected-device names, baseline source/warnings, and override keys.
- Actual versus expected physical orientation/touch/pen behavior, if relevant.
- Whether `platform.py end` succeeded and what remained incorrect.

Monitor/device inventories, configuration paths, journals, and shell logs can reveal personal paths, window titles, or hardware details. Review/redact them before sharing. Do not publish a complete journal, your entire home configuration, private terminal screenshots, or another person's content. A concise sanitized error report is more useful than an unfiltered desktop dump.

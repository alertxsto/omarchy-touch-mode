# Architecture and maintenance

[README](../README.md) · [Install](install.md) · [Configuration](configuration.md) · [Troubleshoot](troubleshooting.md)

## Runtime boundaries

OMARCHY TOUCH MODE shares Omarchy Quattro's long-running Quickshell process. Its bar widget and service are plugin entry points; the keyboard surface is loaded on demand. Native helpers are subprocesses, not separate desktop shells.

```text
Omarchy Quattro / Quickshell
  ├─ BarWidget.qml ── plugin-specific omarchy-shell IPC
  └─ Service.qml
       ├─ Keyboard.qml (only when open)
       │    └─ input-backend.sh → input-helper.c → Wayland virtual keyboard
       ├─ sensor-backend.sh → sensor-helper.c → SensorProxy / system D-Bus
       └─ platform.py → hyprctl → Lua hl.monitor / hl.device
                            ↕
                     private recovery journal

setup.py: explicit diagnostics / example JSON / optional separate Lua mapping
```

Runtime helper paths are resolved relative to QML's own source URL and the shell wrapper's source directory. They do not assume that the repository is named after the plugin ID, that the username matches the manifest author, or that every checkout lives in the normal installed directory.

## Code map

| File | Responsibility |
| --- | --- |
| `manifest.json` | Stable ID `omarkyy.tablet`, public display metadata, Quattro entry points |
| `BarWidget.qml` | Theme-aware drawn keyboard icon; mouse-button dispatch; bar integration |
| `Service.qml` | Tablet/lock state, asynchronous platform actions, sensor events, keyboard Loader, IPC and startup recovery |
| `Keyboard.qml` | Non-focusable layer surface, US key UI, one-shot modifiers/Caps, repeat, dragging/resizing, input-helper lifecycle |
| `input-helper.c` | Stable XKB US keymap and Wayland virtual-keyboard connection; complete evdev strokes |
| `virtual-keyboard-unstable-v1.xml` | Bundled upstream protocol definition, including retained copyright/license |
| `input-backend.sh` | Content-hash build cache, scanner/compiler invocation, build locking, then `exec` input helper |
| `sensor-helper.c` | SensorProxy property validation, accelerometer claim/release, event stream and lifecycle/error cleanup |
| `sensor-backend.sh` | Content-hash native sensor build cache, locking, then `exec` sensor helper |
| `platform.py` | Strict override schema, hardware/baseline discovery, Lua runtime requests, journal/lock, rollback/restoration, command CLI |
| `setup.py` | Read-only doctor, example configuration output, explicit atomic no-overwrite Lua mapping generation |
| `tests/test_platform.py` | Offline hardware-selection and journal behavioral regressions |
| `README.md`, `docs/` | User-facing scope, install/control/config/recovery, technical maintenance |
| `LICENSE` | Project MIT license; upstream protocol notices remain in the XML |

## Keyboard lifecycle and input protocol

Opening the keyboard creates its QML UI and starts `input-backend.sh`. The wrapper compiles if needed, then `exec`s one native helper. That helper:

1. Connects to the active Wayland display and binds a seat plus `zwp_virtual_keyboard_manager_v1`.
2. Builds one `evdev` / `pc105` / `us` XKB keymap for that visible-keyboard lifetime.
3. Sends that map once via an in-memory file descriptor.
4. Prints `ready` after compositor setup.
5. Reads newline-delimited key commands from QML stdin.

Each command is `<Linux evdev keycode> <modifier bits>`. The mask is Ctrl=`1`, Shift=`2`, Alt=`4`, Super=`8`, Caps=`16`. The helper applies modifiers, presses/releases the key, and clears compositor modifiers for each complete stroke. QML retains the UI latch state between strokes and generates held-key repetition; the helper does not keep an arbitrary key physically held while focus changes.

The keyboard is an overlay layer surface with **no keyboard focus** and no reserved desktop area. Pointer/touch goes to its actual window; the focused application continues receiving keyboard input. No full-screen dimmer/grab is used.

Closing/unloading the keyboard ends the process/pipe lifetime and resets its UI modifiers/repeat. Keyboard dimensions live in service properties only for the current shell session. No layout, size, or position persistence schema is implied.

There is no per-key subprocess, transient per-tap keymap, `uinput`, root permission requirement, or text clipboard injection. The C input loop uses a fixed command buffer and does not allocate for each stroke. These properties explain the design; they are not a promise of a particular end-to-end latency or whole-shell memory size.

## Tablet and sensor lifecycle

The service serializes one-shot platform actions with `busy`; repeated control input during an action is not a queue of concurrent transforms. `begin` resolves devices and baseline, writes the journal, and disables the selected optional touchpad. Only a successful begin opens tablet mode and its keyboard.

The sensor process runs only while tablet mode is active and rotation is unlocked. It communicates with:

```text
Bus:       system
Service:   net.hadess.SensorProxy
Object:    /net/hadess/SensorProxy
Interface: net.hadess.SensorProxy
```

`--probe` reads availability/orientation without claiming the sensor. `--watch` claims the accelerometer, emits an initial state and subsequent `PropertiesChanged` events, and runs a GLib event loop. Availability/orientation types and values are validated. Service loss/replacement, bus closure, lost accelerometer, and malformed responses are errors; there are no fake orientation fallbacks.

SIGINT/SIGTERM and parent-pipe shutdown stop the watcher and attempt to release its claim. A vanished/replaced service is not sent a release intended for its previous owner. D-Bus also associates the claim with the connection lifetime. Rotation lock and tablet exit stop the watcher. A watcher failure locks rotation and exposes an error without disabling the independent keyboard.

Orientation maps `normal`→`0`, `left-up`→`1`, `bottom-up`→`2`, `right-up`→`3`; `undefined` does not request a new sensor-derived transform. QML uses a short **one-shot** delay to coalesce events and avoids applying an already-applied transform. There is no idle sensor polling timer and no automatic hinge/fold detection.

`rotate` applies the monitor transform and the selected touchscreen/optional pen transform/output together; it preserves the captured physical mode, position, and scale. Touchpad disabling is reasserted if selected. Failure triggers a baseline restoration attempt. QML stops claiming tablet mode on a failed rotation; platform status/journal remains the authority on whether recovery is still necessary.

## Platform command interface

Run with Python 3 from the source directory:

```sh
python3 platform.py probe
python3 platform.py begin
python3 platform.py rotate 0
python3 platform.py rotate 1
python3 platform.py rotate 2
python3 platform.py rotate 3
python3 platform.py end
python3 platform.py status
```

`probe` is discovery only. `begin`, `rotate`, and `end` are stateful and affect the desktop; the examples above are an interface reference, **not a recommended block to run blindly**. `rotate` requires an active journal. `end` is repeatable and does nothing to monitor/devices if no journal exists.

Successful output is JSON with `ok: true`. Diagnostics go to stderr with a failing exit code. Hyprland requests are made through `hyprctl eval` and Lua `hl.monitor`/`hl.device`, with validated names and safe Lua serialization. A successful subprocess exit is not sufficient: platform control expects Hyprland's `ok` acknowledgement.

Optional pen and touchpad entries are represented explicitly as null/absent when not selected. Their runtime mutation and restoration is skipped, not replaced with guessed devices. See [configuration](configuration.md) for all selection and field-source rules.

## Journal, locking, and restoration

State lives in a private user runtime subdirectory, not the repository or Hyprland config:

```text
$XDG_RUNTIME_DIR/omarkyy.tablet/<session-hash>.json
$XDG_RUNTIME_DIR/omarkyy.tablet/<session-hash>.lock
```

When `XDG_RUNTIME_DIR` is unset, the platform uses `/run/user/<uid>`. The runtime base and plugin state directory must be private and owned by the current user. Files are permission/ownership checked and opened defensively; state is session-bound using `HYPRLAND_INSTANCE_SIGNATURE`. The session signature is hashed for filenames. The journal is versioned and includes the captured baseline, current transform, and action phase.

Journal phases distinguish `beginning`, `active`, `rotating`, and `restoring`. State is written atomically before mutation. A file lock prevents simultaneous CLI actions from racing over the same journal. Valid original version-1 journals remain readable; new optional-device baselines can be null. Invalid/unsafe/unsupported state is an explicit error, never silently discarded.

Restoration attempts every independent applicable monitor/input action. A failure in one does not skip the others. Only completely acknowledged restoration removes the journal; failures retain it for another `end`. Capturing readable runtime fields is preferred, while unreadable fields use the documented explicit/fallback baseline and warnings. No software journal can recover an arbitrary state that the compositor never exposed and the user never declared.

The service attempts `end` during initialization to recover interrupted work. It also attempts detached restoration on destruction when active, but crash cleanup is not guaranteed. Explicit safe exit before reload/update/disable/removal remains important.

## Build cache and resource behavior

Both wrappers use `${XDG_CACHE_HOME:-$HOME/.cache}/omarchy/tablet/`. SHA-256 source hashes distinguish builds; `flock` serializes compilation, and `umask 077` makes newly created artifacts private. Cache generation does not touch the plugin's watched source tree. Helpers replace the wrapper process via `exec`.

Runtime resources are scoped to actual features:

- Keyboard closed: no loaded keyboard surface/input-helper process.
- Keyboard visible: one native Wayland input-helper process.
- Tablet mode with rotation unlocked: one native sensor watcher.
- Rotation locked/tablet inactive: no sensor watcher/claim.
- Platform changes: short-lived Python/`hyprctl` operations, not permanent polling daemons.
- Held repeat: QML timer active only for the supported held keys.

The host shell remains running for Omarchy itself. Quickshell/Qt, drivers, the compositor, and helper state all contribute resource use. Do not publish a “less than 5 MB entire shell” or similar number from the size of one helper. Report any measurements with the exact revision, process boundary, methodology, and hardware.

## Setup, trust, and privacy

The Omarchy plugin installer never invokes install hooks. Dependencies must be installed by the user before first use. `setup.py doctor` only checks prerequisites and reads live APIs. The example-config command prints output. The optional Lua generator is a deliberate user action, writes one separate new file atomically, and prints manual loading instructions; it never edits or creates the main `hyprland.lua`.

Runtime writes are limited to build cache, private recovery state, and the generator's explicitly requested new output. The plugin does not rewrite stock Omarchy toggle files, Hyprland configuration, system settings, or package state. Runtime monitor/device commands remain powerful, so “no sudo” does **not** mean sandboxed or risk-free.

There is no telemetry/upload mechanism in the plugin. Local journals contain display/device baselines and selected names; diagnostics and setup examples can reveal hardware and home paths. Keep those private or redact them before reporting issues. Do not include personal desktop/terminal screenshots as marketing material.

## Development and verification

Keep laptop-specific settings in the external JSON rather than modifying the published source. Do not develop by editing packaged Omarchy shell code or unrelated Hyprland files. Keep `omarkyy.tablet` stable across public display/repository naming changes.

Offline platform regressions can be run by a maintainer:

```sh
python3 -m unittest discover -s tests -v
```

Validate the packaged manifest with the installed Quattro validator:

```sh
omarchy plugin validate /path/to/omarchy-touch-mode
```

Offline tests and manifest validation are not live hardware proof. Before publishing a changed release, separately exercise keyboard-only startup, modifier shortcuts, focus/workspace transitions, hold cancellation, resizing, optional-device absence, sensor failure/lock, tablet entry/exit, recovery, and generator no-overwrite behavior on the target runtime. Physical rotation/touch/pen alignment needs real hardware interaction in every orientation.

The README records narrowly scoped evidence from the original installed implementation; it does not claim that future revisions or all laptops share that calibration. Record what was actually exercised, distinguish command application from physical calibration, and avoid fabricated badges/releases/screenshots.

## Licensing

Project code and documentation use the [MIT license](../LICENSE). The protocol XML contains upstream notices for Kristian Høgsberg, Intel Corporation, Collabora, Ltd., and Purism SPC, together with its permissive license. Retain that notice when distributing the XML or substantial generated copies. Repository ownership/public naming does not erase upstream authorship.

## Publishing to the marketplace

The repository owner/maintainer is [@alertxsto](https://github.com/alertxsto), publishing [alertxsto/omarchy-touch-mode](https://github.com/alertxsto/omarchy-touch-mode). Keep the public display name **OMARCHY TOUCH MODE** and stable manifest ID **`omarkyy.tablet`** distinct.

Follow the [official publishing guide](https://plugins.omarchy.org/publish.html):

1. Publish the real source to a public repository, with a valid root `manifest.json`, README, license, and safe install/removal instructions.
2. Validate the exact packaged revision and confirm its documented commands/entry points match that source. Complete live verification separately; do not label an offline check as physical calibration.
3. Use the official [Submit Plugin issue form](https://github.com/omacom/omarchy-plugin-marketplace/issues/new?template=submit-plugin.yml).
4. Provide the repository URL `https://github.com/alertxsto/omarchy-touch-mode`, category **Hardware**, and tags **Bar**, **Hyprland**, **Quickshell**, using the form's available fields.
5. Describe the supported-runtime and hardware constraints, optional accelerometer, explicit dependency installation, native first-use builds, private recovery state, and reversible removal. Do not claim marketplace approval until an actual listing is approved.

A preview is optional. Only use a deliberately prepared, non-personal image if one is supplied; never capture a user's private terminal or fake a release badge. Marketplace automation validates listings/current commits, not plugin security. Maintainers retain responsibility for dependencies, unsandboxed execution, assets, documentation, license obligations, behavior changes, and future runtime compatibility.

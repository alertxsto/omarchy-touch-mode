# Omarchy Touch Mode

A floating on-screen keyboard and reversible tablet-mode controller for **Omarchy Quattro**. Type with touch or a mouse, rotate a supported laptop display with its real accelerometer, and keep the keyboard accessible from the bar.

![The floating US keyboard with touchable tablet and rotation controls](preview.png)

- **One plugin:** `omarkyy.tablet`; public name **OMARCHY TOUCH MODE**.
- **Keyboard without tablet hardware:** no touchscreen, pen, touchpad, or accelerometer required.
- **Supported laptops detect automatically:** one internal display and one touchscreen; a pen and touchpad are optional. Ambiguous hardware is rejected rather than guessed.
- **Real input:** a native Wayland virtual keyboard with Linux evdev keycodes and a stable US keymap, including Ctrl, Super, Alt, Shift, and Caps.
- **Real sensor events:** SensorProxy over system D-Bus, not simulated orientation or an idle polling loop.
- **Reversible tablet mode:** a private session journal records the desktop baseline before temporary monitor/input changes.
- **No automatic privileged setup:** no package installation, `sudo`, edits to Hyprland configuration, or system configuration changes by the plugin.

## Compatibility and scope

This project targets the **Omarchy Quattro plugin shell**, **Lua-based Hyprland**, and **Quickshell 0.3.1** APIs used by the working installation. It is not a Waybar plugin or a compatibility layer for older/classic Omarchy desktops. A different shell, compositor, or future API revision may require adaptation.

| Feature | Requirements |
| --- | --- |
| Floating keyboard | Running Quattro shell and Wayland session; compositor support for `zwp_virtual_keyboard_manager_v1`; native build dependencies |
| Tablet mode | Lua Hyprland runtime control, one selected active monitor and one selected touchscreen |
| Automatic laptop selection | Exactly one active internal `eDP-`, `LVDS-`, or `DSI-` display and an unambiguous touchscreen |
| Automatic rotation | Tablet-mode requirements plus a supported accelerometer exposed by `iio-sensor-proxy` |
| Touchpad disabling / pen rotation | An identifiable touchpad / pen, when present; either may be omitted or explicitly excluded |

There is **no automatic hinge/fold detection**. You enter and leave tablet mode yourself. Sensor support and touch/pen calibration depend on your hardware and drivers; this is not a guarantee that every convertible laptop will work.

## Install

Review the source before enabling it: Omarchy plugins execute unsandboxed with your user permissions. Marketplace listing or manifest validation is not a security audit.

Install the dependencies yourself first:

```sh
sudo pacman -S --needed base-devel wayland wayland-protocols libxkbcommon glib2 python iio-sensor-proxy util-linux coreutils
```

Then install and enable:

```sh
omarchy plugin add https://github.com/alertxsto/omarchy-touch-mode --enable
```

If already installed but disabled:

```sh
omarchy plugin enable omarkyy.tablet
```

The Omarchy installer clones and validates the repository; it **does not run install hooks**. The native helpers compile into your user cache on first use, not during installation. The keyboard may briefly show “Preparing keyboard…” while its helper builds. Nothing is built or downloaded per keypress.

On supported, unambiguous hardware, there is no required per-laptop editing or touchscreen configuration generation. For a readiness report, run from the installed source directory:

```sh
cd "$HOME/.config/omarchy/plugins/omarkyy.tablet"
python3 setup.py doctor
```

See [installation, first use, updates, and removal](docs/install.md) for the full procedure. Device overrides and a separate, optional Lua mapping generator are described in [configuration](docs/configuration.md).

## Controls

| Control | Action |
| --- | --- |
| Left-click the bar keyboard icon | Show/hide the keyboard |
| Right-click the icon | Enter/exit tablet mode |
| Middle-click the icon | Toggle rotation lock |
| **Tablet** button in the keyboard header | Touchable tablet-mode toggle |
| **Rotation** control in the header (`Auto rotate` / `Locked`) | Touchable rotation-lock toggle |
| Drag the keyboard header | Move the floating keyboard |
| Drag its bottom-right resize handle | Resize; keys, gaps, and labels adapt |
| Header close control | Close the keyboard without exiting tablet mode |

The bar remains visible in tablet mode. It is not replaced or automatically hidden. Open the keyboard with the bar's left-click/touch action to reach the touchable tablet and rotation controls.

The keyboard opens on the focused monitor, near its bottom edge. It does not request keyboard focus or reserve desktop space, so keystrokes go to your focused application. Click/tap a text field in that application before typing.

### Keys and shortcuts

The layout is **US**. The bottom row begins **Ctrl → Super → Alt → Space**. Tap Ctrl, Super, Alt, or Shift to latch it for the next key; a modifier remains active throughout one held repeat sequence and clears on release. Combine modifiers before tapping a key to send shortcuts. Caps stays latched until toggled again; closing/reopening the keyboard resets modifiers.

Hold **Backspace, Delete, or an arrow** to repeat after **350 ms**, then every **45 ms**. Release/cancel, keyboard closure, or workspace/focus changes stop repeat. Other keys do not have this hold-repeat behavior.

The last resized dimensions are kept **only for the current shell session**. The plugin does not persist keyboard size or position in configuration. Keyboard styling follows Omarchy's current shell theme.

### Shell commands

Run these in the active Omarchy session:

```sh
omarchy-shell omarkyy.tablet keyboard
omarchy-shell omarkyy.tablet tablet
omarchy-shell omarkyy.tablet rotationLock
omarchy-shell omarkyy.tablet off
omarchy-shell omarkyy.tablet status
```

`keyboard`, `tablet`, and `rotationLock` are toggles. `off` always attempts tablet recovery/exit, even if the service currently reports tablet mode inactive; successful completion also closes the keyboard. `status` reports the shell service's current state as JSON. These are plugin-specific IPC methods, not the generic shell panel summon API.

## What tablet mode changes

1. Resolve hardware and capture the monitor/input restoration baseline.
2. Write a private, session-specific recovery journal **before** changes.
3. Disable the selected touchpad, if present, and open the keyboard.
4. When rotation is unlocked, claim the accelerometer and listen for orientation events.
5. Apply the display transform and map the selected touchscreen/optional pen to the selected display together.
6. On exit, restore the recorded monitor mode, position, scale, transform, touch/pen mapping, and touchpad enabled state; close the keyboard and release the sensor.

Rotation lock stops automatic rotation and releases the accelerometer claim; it does not exit tablet mode or restore the desktop. Closing only the keyboard also leaves tablet mode active.

Hyprland does not expose every current per-device option on the target API. When a runtime field is unreadable, the plugin uses an explicit [input baseline](docs/configuration.md#restoration-baselines), or a documented normal-orientation/default mapping assumption, and reports warnings. It cannot capture arbitrary unreadable runtime overrides. **Read these warnings before using tablet mode**, especially with an existing custom touch/pen mapping.

Exit tablet mode before editing or reloading Hyprland configuration, changing device overrides, updating, disabling, or removing the plugin. A compositor reload may replace temporary runtime options; it is not a tablet-mode exit.

## Recovery

If the shell disappears or a tablet operation is interrupted, run the recovery command in a terminal belonging to the **same live Hyprland session**:

```sh
python3 "$HOME/.config/omarchy/plugins/omarkyy.tablet/platform.py" end
```

The journal survives plugin/shell reloads within that session, and the service attempts recovery automatically when it starts; no journal means no monitor/device changes. Restoration attempts independent monitor and device actions; an incomplete restoration retains the journal so `end` can be retried after resolving the reported error. Do not delete the journal to silence an error. See [troubleshooting and recovery](docs/troubleshooting.md).

## Update or remove

Exit tablet mode and wait for `busy` to become false in `status` first:

```sh
omarchy-shell omarkyy.tablet off
omarchy-shell omarkyy.tablet status
omarchy plugin update omarkyy.tablet
```

For removal, use the same exit procedure before:

```sh
omarchy plugin remove omarkyy.tablet
```

If IPC is unavailable, use `platform.py end` **before removing the source files**. User-owned device configuration, optional generated Lua mappings, and cache files are not silently removed; [the install guide](docs/install.md#disable-and-remove-safely) explains their ownership.

## Verification and limitations

The packaged release was exercised on this laptop: automatic hardware discovery, actual QML key clicks into a GTK TextView, Shift and Ctrl+A, held Backspace with release cancellation, resizing, command-level display transforms `0/1/2/3`, a real accelerometer `normal` event, failed sensor-watcher locking, tablet exit, and startup recovery of a live journal. Both native helpers also built and connected from source/cache paths containing spaces. Eight offline hardware-selection/journal regressions passed; the Lua generator rejected existing files, symlinks, and the main configuration filename. The original implementation additionally exercised Super+1 and held arrows.

Applying all transform values from a command verifies runtime control, not physical alignment. Rotating the actual machine through each orientation and tapping/drawing near every screen edge are still required to establish touchscreen and pen calibration on a particular device. Automatic portable hardware discovery does not establish sensor mounting correctness, touch accuracy, or universal compatibility.

The keyboard currently has a fixed US layout; there is no layout picker, handwriting engine, or automatic application-specific layout switching. Resource use depends on the shared shell, display, and drivers. No whole-shell memory-size guarantee is made.

Application-specific focus behavior is not universally verified. A single-line GTK Entry target replaced earlier characters during the pointer-driven smoke scenario; the GTK TextView target accumulated text correctly. If typing replaces text, inspect selection/focus behavior and report the application and reproduction; do not assume every text widget is covered by the TextView verification.

## Documentation

- [Install](docs/install.md): dependencies, first use, readiness checks, updates, disable/removal.
- [Configure](docs/configuration.md): exact device schema, detection rules, restoration assumptions, optional Lua mapping.
- [Troubleshoot](docs/troubleshooting.md): sensor/input issues, focus/keymaps, ambiguity, logs, safe recovery, useful bug reports.
- [Architecture and maintenance](docs/architecture.md): code map, process lifecycles, state/privacy, licensing, marketplace submission.

## License and ownership

Project code and documentation are licensed under [MIT](LICENSE). The bundled `virtual-keyboard-unstable-v1.xml` retains its upstream permissive license and copyright notices; those notices must remain when redistributing the protocol or generated substantial copies.

Repository: [alertxsto/omarchy-touch-mode](https://github.com/alertxsto/omarchy-touch-mode). Maintainer: [@alertxsto](https://github.com/alertxsto). The historical plugin ID `omarkyy.tablet` and user configuration directory `~/.config/omarchy-tablet` are intentionally stable so existing installations keep their settings; neither is derived from the repository name or owner's current username.

This is an independent community plugin, not an official Omarchy component. Maintainers remain responsible for its behavior, dependencies, documentation, license, and safe installation/removal. Marketplace submission follows the [official publishing guide](https://plugins.omarchy.org/publish.html); instructions and the submission form are linked in [architecture and maintenance](docs/architecture.md#publishing-to-the-marketplace).

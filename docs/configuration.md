# Configuration and hardware selection

[README](../README.md) · [Install](install.md) · [Troubleshoot](troubleshooting.md)

## Zero-config supported hardware

The keyboard is independent of tablet hardware and needs no device configuration. Tablet mode probes the live Hyprland session on entry. A supported, unambiguous laptop can work without a configuration file:

- Exactly one active internal monitor whose name begins `eDP-`, `LVDS-`, or `DSI-`.
- Exactly one touchscreen in Hyprland's touch device list.
- Zero or one pen/tablet candidate; no pen is valid.
- Zero or one touchpad candidate; no touchpad is valid.

Multiple candidates are **not** resolved by list order, a hardcoded vendor name, or an arbitrary preferred device. Specify exact names to resolve ambiguity. The auto touchpad selector identifies touchpad candidates from the mice list; other mice are not automatically disabled. If your touchpad does not identify as such, select its exact name explicitly.

Use the current session's inventory, not names copied from another laptop:

```sh
hyprctl -j monitors
hyprctl -j devices
python3 "$HOME/.config/omarchy/plugins/omarkyy.tablet/platform.py" probe
```

`probe` reads hardware and baseline information; it does not enter tablet mode. Its JSON includes `monitor`, `touch`, nullable `pen`/`touchpad`, `warnings`, `configFile`, and optional-device selection status. The JSON probe key is `touch`; the user configuration key is **`touchscreen`**.

## User-owned configuration file

The fixed configuration path is:

```text
~/.config/omarchy-tablet/config.json
```

The historical directory name is retained even though the public name is OMARCHY TOUCH MODE and the repository is `omarchy-touch-mode`. This file belongs to you and is outside the git-managed plugin checkout. The plugin reads it; it does not create or rewrite it automatically.

**Exit tablet mode and complete restoration before changing the file.** The captured journal, not a newly edited configuration, governs restoration of an existing session. New overrides take effect at the next probe/begin.

Only these top-level keys are supported. Unknown keys, duplicate JSON keys, and invalid value types are rejected rather than silently ignored:

| Key | Value | When omitted |
| --- | --- | --- |
| `monitor` | Exact active Hyprland monitor name, nonempty string | Auto-select one active internal panel |
| `touchscreen` | Exact touch device name, nonempty string | Auto-select one touchscreen; required for tablet mode |
| `pen` | Exact pen/tablet name, or `null` to exclude all pen handling | Auto-select if unique; zero candidates is allowed |
| `touchpad` | Exact mouse-list device name, or `null` to exclude touchpad handling | Auto-select a unique touchpad; zero candidates is allowed |
| `input_baseline` | Object of explicit touch/pen restoration fields | Read runtime fields when exposed; otherwise use warned fallback assumptions |

`null` is allowed only for `pen` and `touchpad`. It means “do not select or mutate this optional device,” not “try autodetection.” Omission means autodetection. `false` is not an alias for `null`. Monitor and touchscreen cannot be disabled via `null`; use the keyboard alone if tablet mode is not wanted.

Names must match **Hyprland's reported names exactly**, including punctuation. An explicit name that does not exist is an error; it is not silently replaced by another device. An explicit monitor override permits selecting a non-internal active display, but you remain responsible for choosing a valid touchscreen/display pair. Auto-selection is the internal-laptop rule, not a guarantee of correctness for an external display.

### Minimal examples

Exclude optional devices without hardcoding the required ones:

```json
{
  "pen": null,
  "touchpad": null
}
```

Select a monitor explicitly, leaving other devices automatic (replace `eDP-1` with the actual name):

```json
{
  "monitor": "eDP-1"
}
```

To obtain a full example with names from the current machine:

```sh
python3 "$HOME/.config/omarchy/plugins/omarkyy.tablet/setup.py" example-config
```

This prints JSON, not a file. If discovery fails, the helper reports that fact on stderr and uses neutral example names; these are not valid hardware choices until you replace them. Review the output, then save only the overrides you need in the user-owned config file. Do not blindly redirect over an existing configuration.

## Restoration baselines

The plugin captures monitor mode, position, scale, and transform from Hyprland. Touch/pen output and transform, and touchpad enabled state, are captured from runtime data **when the API exposes them**.

The target Lua Hyprland API may omit per-device fields. A missing field is not evidence of a default setting. For each unreadable touch/pen field, the restoration precedence is:

1. Runtime value, if actually exposed.
2. Explicit matching `input_baseline` value in your JSON.
3. Assumed transform `0` or output equal to the selected monitor, with a warning.

Each field is resolved independently. Explicit baseline values do not override a readable runtime value. A selected touch/pen entry in probe output reports `source` and `field_sources` so you can see whether values came from `runtime`, `config`, or an assumed normal baseline; mixed sources are possible.

`input_baseline` accepts only `touchscreen` and `pen` objects. Each may contain `transform`, `output`, or both:

| Field | Allowed value | Meaning |
| --- | --- | --- |
| `transform` | Integer from `-1` through `7` | Your existing Hyprland device transform to restore |
| `output` | String, including the empty string | Your existing output mapping to restore |

For example, if your existing normal-orientation mapping is transform `0` to `eDP-1`:

```json
{
  "input_baseline": {
    "touchscreen": {
      "transform": 0,
      "output": "eDP-1"
    },
    "pen": {
      "transform": 0,
      "output": "eDP-1"
    }
  }
}
```

This is an **example**, not a calibration preset. Use your actual baseline. An empty output string and a transform such as `-1` can be intentional; do not normalize them to `eDP-1` and `0` merely to suppress warnings. If a pen is absent/excluded, its baseline is not mutated.

There is no automatic parsing or presumed loading of `~/.config/hypr/touchscreen.lua`. The JSON records your declared restoration assumptions; it does not install those assumptions into Hyprland's persistent config. Keep the JSON baseline consistent with the persistent mapping that you actually load.

For an unreadable touchpad enabled state, the plugin consults the stock Omarchy persisted disabled-name state at:

```text
~/.local/state/omarchy/toggles/hypr/touchpad-disabled-name
```

It reads this file as data, never sources or rewrites it. The fallback is reported as `omarchy-persisted-toggle-fallback`. An arbitrary unpersisted runtime override cannot be captured through an API that does not expose it. If that distinction matters on your machine, establish a known baseline before entering tablet mode.

## Optional persistent Lua touchscreen mapping

A standalone mapping can be useful if touch/pen should map to the chosen monitor outside tablet mode too. It is **optional** and separate from plugin installation. The generator never edits your main Hyprland configuration or auto-loads its output.

First exit tablet mode and confirm restoration is complete. Inspect probe warnings and any existing mapping. Choose an output path whose parent directory already exists and whose file does **not** exist:

```sh
python3 "$HOME/.config/omarchy/plugins/omarkyy.tablet/setup.py" write-touchscreen-config "$HOME/.config/hypr/omarchy-touch-mode-input.lua"
```

The command:

- Resolves the selected touchscreen and optional pen.
- Writes standalone Lua `hl.device(...)` mapping blocks using the resolved baseline, not a claimed physical calibration.
- Creates the file privately with mode `0600` and atomic no-overwrite behavior, including refusal to overwrite a symlink.
- Prints the **exact absolute `dofile(...)` instruction**, a `require` alternative, matching `input_baseline` JSON, and any warnings.
- Does not create the parent directory, install packages, edit `hyprland.lua`, or reload Hyprland.

Review the generated Lua before loading it. Manually add the printed load instruction to your user-owned Lua Hyprland configuration, in the location/order appropriate to your configuration. `dofile` with an absolute path is the direct option. `require` is suitable only if the module is on your configured Lua module search path; use the helper's printed instructions rather than assuming every filename/directory is importable.

Do not add both `require` and `dofile` for the same file. Avoid duplicate device blocks that later override the mapping. Set the corresponding JSON `input_baseline` fields to the intended persistent baseline if runtime fields are unreadable. Any configuration reload should happen **outside tablet mode**.

A refusal because the file exists is expected safe behavior. A destination named `hyprland.lua` is also explicitly rejected, even if absent: the generator is for a separate mapping file, not a new main configuration. Inspect/edit your existing mapping yourself, or choose a new output filename; the generator is not an overwrite/update command.

## Rotation interpretation

Sensor orientation maps to transform values as follows:

| SensorProxy orientation | Display/touch/pen transform |
| --- | --- |
| `normal` | `0` |
| `left-up` | `1` |
| `bottom-up` | `2` |
| `right-up` | `3` |
| `undefined` | No new sensor-derived orientation |

Only transforms `0`, `1`, `2`, and `3` are accepted by the explicit `platform.py rotate` action. Other baseline transforms remain valid restoration values. A short one-shot delay coalesces sensor changes; it is not periodic polling.

Sensor mounting, firmware information, and touch/pen hardware coordinate mapping may differ. No per-model physical calibration or custom sensor-orientation remapping is configured by this schema. Test your actual hardware; if the stock mapping is incorrect, lock rotation/exit tablet mode and report evidence rather than repeatedly changing unrelated baseline fields.

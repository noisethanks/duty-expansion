# Tools

Offline checks for the mod. Neither tool changes any file or needs the game running. Run both from the repo root before every release.

## scan_animation_states.py

Checks every animation state that this repo's LTX files use against two sources, so a state that works in base Anomaly but breaks in GAMMA shows up.

- `base` is the unpacked Anomaly scripts and meshes only.
- `gamma` is the active MO2 profile: `overwrite`, then the enabled mods in `modlist.txt` order, then base.

For each state the scan follows `state_lib`, `state_mgr_animation_list` and `state_mgr_animstate_list` to the motion names. It expands `@random` points through `xr_animpoint_predicates.associations`. It then checks that every motion exists in the four omf files that Anna's model references. Attach and detach tables (`a=`, `d=`), sounds and function hooks are item sections or callbacks, not motions, so the scan skips them.

Command:

```
python3 -I tools/scan_animation_states.py
```

The defaults point at `~/gamma/anomaly/tools/_unpacked` and `~/gamma/gamma` with the profile `AlifePlusandQuests`. Use `--base`, `--gamma` and `--profile` to change them, and `--all` to list passing states too.

A pass prints an empty table and ends with this line, and the exit code is 0:

```
49 states checked, 0 fail in at least one source, 4 mutant animation names skipped
```

The count of states changes when the LTX changes. A failing state prints one row with a category:

| Category | Meaning |
| --- | --- |
| `UNDEFINED` | The state, or its animation list entry, does not exist in either source |
| `BASE-ONLY` | It fails in base Anomaly and resolves in GAMMA |
| `GAMMA-ONLY` | It resolves in base Anomaly and fails in GAMMA |
| `BOTH` | It fails in both sources |

The release rule is that every state resolves in both sources, so any row is a failure and the exit code is 1.

The scan does not check engine movement and stance motions, runtime table writes by other mods (it prints a warning for any it finds), or the visuals of NPCs other than Anna. The outpost NPCs are assumed to use the same four omf files. Two base Duty models were checked and both reference them.

## anchor_harness.lua

Runs the anchor resolver in `duty_redux_logic.script` against `configs/scripts/duty_redux/anchors.ltx` with the engine stubbed out. It also calls `debug_anchors()` once.

Command:

```
lua5.1 tools/anchor_harness.lua
```

A pass prints one `PASS <check>` line per check, the log lines the script writes, and `ALL PASS` at the end, with exit code 0. A failure prints `FAIL <check>` and ends with `<n> FAILED` and exit code 1.

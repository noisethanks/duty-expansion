# Anna Redux: Behavior Design Spec

Oct 19, 2026 · @Abhishek Mallepalli

## Purpose and scope

Redux rebuilds Anna's behavior so the Duty Expansion can ship enabled by default in the next GAMMA release. This spec covers her idle life at Rostok first. The same architecture then carries her four quest stages and post-quest companion mode.

Out of scope: dialog text, quest rewards, and quest design changes. Those stay as they are unless this work exposes a bug in them.

## Acceptance criteria

Redux is ready for default enablement when every item below holds.

1. **No crash in any supported save state.** Fresh game, every quest stage, companion mode, mid-surge, and mid-transition between levels.
2. **No file ownership.** All changes to base or shared files go through DLTX and DXML. The mod ships only files it owns outright.
3. **Coexists with Rostok.** No conflict with bar smart terrain jobs, the surge manager, companion logic, or other GAMMA mods touching Duty NPCs.
4. **Fails soft.** A bad position, missing squad, or unexpected state degrades her behavior. It never stops level load.
5. **Save compatible across Redux versions.** Any Redux save loads in any later Redux version. Saves from pre-Redux versions are not supported.
6. **Documented behavior.** This spec stays in the repo and matches what ships. PRs are reviewed against it.
7. **Installs into an existing save.** Installing Redux into a save that never had the Duty Expansion is supported. It loads and runs, and Anna spawns at Rostok. Verified working. A save made with an older version of the mod is not supported, as criterion 5 says.

Removal policy is still open: either Redux supports uninstall from a live save, or the docs state clearly that it does not.

## Character

Anna is a Duty soldier stationed at Rostok with a routine, not a statue at a fixed point. This section is a starting proposal to revise before implementation.

- **Role:** gate guard by day, off duty in the evening, sleeps in the bunker. This matches the existing schedule.
- **Temperament:** disciplined on duty, more relaxed off duty. Her body language should change between the two.
- **Relationship to the player:** neutral before the intro dialog, familiar after it, trusted after the questline.

What a player should notice over several visits:

- She is findable at predictable times, but not frozen in the same pose every time.
- She moves between places on foot, visibly, at shift changes.
- She reacts to the world: shelter in a blowout, cover from rain, other Duty NPCs nearby.
- After the questline, she acknowledges the player differently.

## Architecture

Redux splits her behavior into layers so position bugs are solved once, as a class. Each layer only talks to the one below it, and only the anchor layer knows coordinates.

&#91;embedded content: Redux behavior architecture · 5 layers\]

The anchor layer is the fix for the Rostok crashes: a stale coordinate becomes a logged warning and a fallback position, never a failed level load.

## Engine and tooling

Redux targets the current xray-monolith modded exes and uses vanilla xr\_logic schemes for movement and animation. The exes add the patching, validation, and debugging tools that make that approach maintainable. The reference for every export is `lua_help_ex.script` in the [xray-monolith repo](https://github.com/themrdemonized/xray-monolith).

| Capability | What it gives Redux | Use |
| --- | --- | --- |
| DXML | Patches character\_desc and dialog lists at read time without owning the file | Anna's profile, dialogs, any base XML change |
| DLTX | Patches LTX sections without owning the file | Squad, spawn, and smart terrain additions |
| `level.vertex_id` and nav queries | Checks whether a position sits on valid navigation | Anchor validation at load |
| `debug_render` shapes | Draws spheres, lines, and boxes in the world | Visualize every anchor and route while developing |
| LuaPanda debugger | Step-through Lua debugging from VS Code | Tracing scheme switches and condlists |
| `is_valid()` on game objects | Safe check that a script object still points at a live object | Guarding every cached reference to Anna |
| Callback priority system | Controls execution order between mods on the same callback | Running our hooks before or after other Rostok mods |
| Per-NPC AI setters | Recent additions for aim, vision, fire rate, hit reactions | Quest combat tuning later, not idle |

**Movement runs on the mod's own framework.** Anna does not use stock `axr_beh` point handling. `target = %=redux_animpoint()% nil` routes her through `duty_redux_logic.script` (derived from GhenTuong's `xr_logic_ex.script`), which has its own point parser, mover, and priority logic switcher. Redux owns that code, so anchors and validation go there. New engine levers are mostly combat oriented and belong to the quest stages.

**No new dependencies.** A-Life Plus and xlibs are out of scope for Redux. Everything above ships with the modded exes GAMMA already requires.

## Code findings

A read-only pass over `xr_logic_ex.script` (now `duty_redux_logic.script`) and `axr_beh.script` on 2026-10-21 established how her behavior actually runs.

| Area | Finding | Consequence for Redux |
| --- | --- | --- |
| File collision | Western Goods ships a functionally identical `xr_logic_ex.script` at the same path. Both copies would act on any squad with `logic =` | Rename the script and the squad key so only Redux processes her. Done in step 3 as `duty_redux_logic.script` and `redux_logic =` |
| WG hooks stay active | Renaming the script and squad key is not enough. Western Goods' copy is still loaded and registers its own `npc_on_net_spawn`, `npc_on_before_hit` and `npc_on_eval_danger` hooks. They act on any NPC whose logic file carries the keys they read. On 2026-10-25, fast travel into Rostok crashed with `CAI_Stalker::net_Export !NET.empty()`. WG's `npc_set_position` (`xr_logic_ex.script:1063`) read `net_spawn` from her logic section and teleported her during net spawn | Every key that only the framework reads gets a `redux_` prefix: `redux_net_spawn`, `redux_danger_ignore`, `redux_combat_camper_state_fire`, `redux_combat_camper_state_look`, `redux_move_animation`, `redux_wait_animation`, `redux_before_hit`, and `redux_target` in `mob_home` sections. WG's copy is active alongside ours, so no LTX in this repo may contain a key it reads, except the stock ones below |
| Stock keys kept | `target` in `beh` sections is read by stock `axr_beh.script` and carries `%=redux_animpoint()%`. WG reads `target` only in `monster_on_update`, which fires for monsters, and `mob_home` sections use `redux_target`. The `[section@squad]` and `[section@logic]` sections and the `suitable`, `prior` and `target@` keys are read by WG only for squads that have a `logic =` key, which no squad here has. `combat_ignore_cond`, `enemy_ignore_cond` and `no_combat_job` are stock keys, and both copies override `ignore_enemy_by_overrides` identically | No rename needed. Both copies also replace `xr_combat_camper.action_shoot` and `action_look_around`, so whichever loads last wins the function. Renaming the keys does not change that |
| Point format | `delay,anim,sound_idle` before the bar. Delay is in milliseconds, so 999999 is about 16.7 minutes | Activities can use real wait times |
| Point tags | `pos:`, `animpoint:`, `dir:` (yaw), `look:` | Add an `anchor:` tag resolved here |
| Chaining | `pt1..ptN` always loop. `path_end` is ignored. `@random` re-rolls the animation on each reload | Variety within an activity needs config only |
| Validation | No check on `pos:` anywhere. An off-mesh position returns 4294967295, which passes the nil check and leaves her in the wait pose indefinitely | Validate in `load_animpoint` and `npc_set_position` |
| Net spawn | `redux_net_spawn = pt1` teleports to the raw position. Typo at XLE:1010 checked `p[1]` three times | Fixed in the anchor pass |
| Switcher | `suitable` re-evaluates every squad update. `active` is evaluated once at switch time | Random activity choice must be rolled once and stored |
| Ties | Current logic wins ties. Equal priors among new candidates resolve in hash order | Keep priors distinct or conditions disjoint |
| No suitable logic | She stays in her current logic even if unsuitable | `logic@idle` with `suitable = true` must stay |
| Cache | Logic priors and conditions are cached in the save and cleared only on level change | Tests need a level change after edits. Version bumps must clear the cache |
| Patch hooks | `axr_beh_patches.script` deployment is unconfirmed | Do not depend on it |

## Activity catalog and daily schedule

Each time slot picks from a weighted set of activities, so she is findable by slot but varies within it. Anchor names below are placeholders until positions are surveyed in game.

| Activity | Anchor zone | Behavior | Talkable |
| --- | --- | --- | --- |
| Gate guard | West gate (`bar_zastava_2`) | Guard stance, occasional look-around and repositioning between two or three gate points | Yes |
| Wall patrol | Base perimeter | Walks a short loop between gate and wall points, pauses at each | Yes, when stopped |
| Weapon maintenance | Barracks or gate | Sits and cleans weapon | Yes |
| Meal | Bar or mess | Sits at a table, eats | Yes |
| Off duty at the bar | 100 Rads (`bar_dolg_general` area) | Sits or stands at the counter, drinks | Yes |
| Campfire | Duty camp spot | Authored sit and idle points at the camp. Smart terrain jobs skip her squad, so this is not a terrain job | Yes |
| Smoke break | Near barracks | Stands, smokes | Yes |
| Sleep | Bunker (`bar_dolg_bunker`) | Sleep animpoint | Sleep dialog only |

| Slot | Activities (weight) |
| --- | --- |
| 05:00 to 06:00 | Meal 70, smoke break 30 |
| 06:00 to 12:00 | Gate guard 70, wall patrol 30 |
| 12:00 to 13:00 | Meal 80, smoke break 20 |
| 13:00 to 18:00 | Gate guard 50, wall patrol 30, weapon maintenance 20 |
| 18:00 to 19:00 | Weapon maintenance 50, smoke break 50 |
| 19:00 to 23:00 | Off duty at the bar 60, campfire 40 |
| 23:00 to 05:00 | Sleep 100 |

Weights are first-pass values to tune in play. Re-rolls happen at slot boundaries and optionally every 30 to 60 in-game minutes within long slots.

The current routing leaves 18:00 to 19:00 and 23:00 to 24:00 uncovered by any on-level activity. That is inferred from the documented condlists and worth confirming, since uncovered slots fall through to idle.

## Override rules and handoffs

Overrides preempt the schedule in a fixed precedence, highest first. Each one must hand control back cleanly when its condition ends.

1. **Combat.** Engine combat AI takes over. On exit she returns to the current slot's activity, not the one she left.
2. **Companion mode.** After the questline and when recruited, companion logic owns her. Idle and quest logic stay fully inactive.
3. **Quest stage active.** Squad routing and on-level logic follow the quest. Idle resumes only after the stage's done token is set.
4. **Surge.** She moves to the nearest valid shelter anchor and holds there until the surge ends.
5. **Rain.** Outdoor activities swap to their sheltered variant. Optional for the first release.
6. **Schedule.** The weighted activity for the current slot.
7. **Fallback.** If nothing else resolves, a safe guard stance at a validated anchor inside the base.

Handoff rules:

- Every override checks a single source of truth for her state, rather than each scheme reading tokens independently.
- No override assumes she is online. Offline progression must reach the same state through squad routing alone.
- Companion mode and quest stages never run at the same time. Entering one clears the other.
- The existing Hip mutex stays: if Hip is the active companion and simultaneous companions are off, Anna leaves the companion squad.

## Save compatibility and state model

Any Redux save must load in any later Redux version. Pre-Redux saves are unsupported and Redux refuses to run on them with a clear message rather than a crash.

Two install cases decide whether a save is supported:

- **A save that never had the mod is supported.** Redux installs into it and Anna spawns at Rostok. This is verified working.
- **A save made with an older version of the mod is not supported.** Redux detects it and refuses to run.

What a save is allowed to depend on:

- **Info tokens.** The existing `duty_girl_*` tokens are the public contract for quest progress. Names never change once shipped.
- **Story ids.** `squad_duty_girl` and the character section `stalker_duty_girl` stay fixed.
- **One versioned state record.** Redux keeps its own state (current activity, last roll time, version) in the game's script save storage under a single key, with a `redux_version` field.
- **Logic section names.** Saved NPC state can reference the active scheme section. Once shipped, a section name is never deleted. Retired sections become aliases of their replacement.

What a save must not depend on:

- Raw positions. Anchors are looked up by name at runtime, so moving one never breaks a save.
- Weights, timings, and activity lists. These are config, read fresh on load.

On load, a migration step reads `redux_version` and upgrades the state record in order, one version at a time. A missing record on a save that has `duty_girl_init` means a pre-Redux save.

The version stamp ships first, from 0.1.0-beta. `save_state` writes `REDUX_VERSION` to the `redux_version` key of the script save storage. On load, `on_game_load` logs `save stamp <version>`. If the stamp is missing on a save that has `duty_girl_init`, it logs `pre-Redux or pre-stamp save` and does nothing else. The check runs on actor net spawn, before `gameplay_duty_girl` sets `duty_girl_init` on first update, so a fresh install is not reported. Beta saves carry the stamp, so a later version can tell them apart from pre-Redux saves. Migration, cache clearing and refusal are still step 5.

The framework caches each logic's prior and suitable condition in the save. A version bump must clear that cache during migration, or an updated Redux keeps running the previous version's logic table until the next level change.

## Test plan

Every combination below is reachable from one throwaway save using console time changes, surge triggers, and info tokens given directly.

| Dimension | Values to cover |
| --- | --- |
| Time slot | Each slot in the schedule, plus one minute either side of every boundary |
| Player presence | On level at the transition, arriving mid-slot, arriving mid-walk |
| World state | Normal, surge active, surge ending, rain |
| Quest state | Not started, intro done, each quest stage, all done |
| Companion | Not recruited, recruited, recruited alongside Hip |
| Save cycle | Save and reload in each state above, then load in the next Redux build |
| Install point | New game, and installing Redux into an existing save that never had the mod (supported, verified working). A save from an older mod version is out of scope and must be refused |
| Load order | Redux alone, then with the full default GAMMA list |

Checks for each run:

- Level loads with no Lua error and no fatal.
- She is at the slot's anchor zone within a few in-game minutes.
- The activity matches one of the slot's options.
- She is talkable where the catalog says so.
- `debug_render` overlays match where she actually stands.

Anchor validation runs once per level load and logs every anchor that fails, so drift shows up in the log before anyone files a crash report.

### Diagnostic logging

Every line starts with `Redux logic:` so one search finds all of it in the log. Lines are built with `string.format` and written with `printf("%s", line)`, so a `%` in a name never reaches the engine format.

- **Version line.** `Redux logic: Duty Expansion Redux <version>` prints once on game start. The version comes from `REDUX_VERSION` in `duty_redux_logic.script`. Bug reports must include it.
- **`duty_redux_logic.debug_anna()`.** Prints Anna's squad id and object id, online status, current level, `section_logic`, `active_section`, the state manager target state, the animation marker, the active item and best weapon sections, `best_enemy`, `best_danger`, and every `duty_girl_*` info token that is set. When she is offline it prints the ids, the level and the tokens, and skips the object state. When she is not spawned it prints one line saying so. It never throws.
- **`duty_redux_logic.debug_anchors()`.** Prints every anchor on the current level with its position, yaw, level vertex, validity and fallback, then every anchor problem logged for that level.
- **Automatic calls.** `debug_anna()` runs once per level entry, on the first squad update after Anna is online on that level. It does not wait for her logic to have an active section, so a missing one shows in the log line. It also runs once each time a `duty_girl_*` info token is given, which covers every quest stage change. It never runs per tick.

Run either function from the console with `run_string duty_redux_logic.debug_anna()`.

### Pre-release checks

Run these before every public release.

1. **Animation scan.** Run `python3 -I tools/scan_animation_states.py`. The scan lists every animation state the mod's LTX files reference. That means `pt` states, `close_anim`, `run_anim`, `walk_anim`, `jog_anim`, `wait_anim`, the `redux_` variants and the camper state keys. It expands every `@random` point through `xr_animpoint_predicates.associations`. It resolves each state through `state_lib`, `state_mgr_animation_list` and `state_mgr_animstate_list` to its motion names. Then it checks that each motion exists in the omf files Anna's model references: `stalker_animation`, `stalker_scripts_animation`, `stalker_smart_cover_animation` and `stalker_scenario_animation`. Most script-driven motions live outside `stalker_animation.omf`, so a miss there alone is not a failure.

   The scan checks two sources separately. `base` is the unpacked Anomaly files only. `gamma` is the active MO2 profile, using the copy of each file that wins there. The release rule is that every state resolves in both. A state that fails prints as `UNDEFINED`, `BASE-ONLY`, `GAMMA-ONLY` or `BOTH`, and the exit code is 1. Attach and detach tables such as `{a="bread"}` name item sections, not motions, so the scan skips them. The scan is read-only and changes no state. `tools/README.md` has the command options and what a pass looks like.

   Last run on Nov 6, 2026: all 49 states resolve in both sources. Before the run, the Duty Outpost NPC points used three states that failed. `dynamite` is undefined in both sources because `state_mgr_animation_list` has no `dynamite` entry. `drunk_behindwall` and `animpoint_sit_ass_use_pda` resolve in base Anomaly but not in GAMMA, because the GAMMA omf files lack `drink_idle_5_0` and the `item_5_*_1_*` motions. Those points now use `hide_no_wpn`, `animpoint_stay_wall_drink_vodka` and `animpoint_sit_knee@random`. The scan does not cover engine movement and stance motions, runtime table writes by other mods, or the visuals of the outpost NPCs.

2. **Anchor harness.** Run `lua5.1 tools/anchor_harness.lua`. It loads `duty_redux_logic.script` with the engine stubbed out and checks the anchor resolver and `debug_anchors()`. A pass prints `ALL PASS` and exits with code 0. `tools/README.md` has the details.

## Implementation plan

Each step ships working behavior and is verified in game before the next starts. Steps 1 to 4 are infrastructure with no intended visible change.

1. **Version control baseline.** Done. The existing public repo is kept, with `.gitattributes` (`* -text`), `.gitignore`, and this spec under `docs/`.
2. **Project rules.** A `CLAUDE.md` in the repo: preserve encodings and line endings, never commit or push, change levels after LTX edits before testing.
3. **Namespace the framework.** Rename `xr_logic_ex.script` to `duty_redux_logic.script` and the squad key from `logic =` to `redux_logic =`. Injected conditions and effects get a `redux_` prefix, and the `before_hit` key and `[on_changing_level]` section get the same prefix. The crash above extended this to every key that only the framework reads, as listed under Code findings. Update `ignore_smart_job` to check the new key, or Rostok smart terrains start assigning her jobs. Done when her behavior matches the baseline and terrains still ignore her.
4. **Anchors.** Named anchor table, an `anchor:` tag resolved in `load_animpoint` and `npc_set_position`, validation against `4294967295` rather than nil, `npc:accessible` before `accessible_nearest`, logging on failure. Fix the XLE:1010 typo and the nil position passed to `set_npc_position`. Convert the five Rostok positions with no position changes.
5. **Versioned state and cache invalidation.** The Redux state record with `redux_version`, and migration that clears the logic cache on a version bump. Partly done. The version stamp is saved and logged from 0.1.0-beta. Migration, cache clearing and refusal of pre-Redux saves are still open.
6. **Schedule gaps.** Cover 05:00 to 06:00, 18:00 to 19:00, and 23:00 to 24:00, and align squad routing with on-level logic in those slots.
7. **Roll-once activity selection.** Mechanism first, using only existing activities.
8. **Surge.** Choose shelter by distance, register her in the surge manager ignore list from Redux, add shelter behavior on quest levels.
9. **Separate idle from quest logic.** Idle sections stop inheriting quest sections and their transitions.
10. **File ownership cleanup.** Partly done.
    - **Done.** The smart terrain file is now the DLTX patch `mod_red_smart_terrain_bridge_duty_expansion.ltx`. It no longer replaces the G.A.M.M.A. NPC Spawns copy. Every section header uses `@[`, so a full copy from an older Duty Expansion version merges instead of duplicating.
    - **Open, deferred to a later audio refactor.** Move the two `meet_hello` sounds to a unique path, since they currently replace GFY's shared female greetings. Hip and two other characters share that folder. The preferred approach is a sound theme override keyed to her story id, with her `close_snd_hello` pointing at it. That keeps her on GFY's voice for every other line.
    - **Not a concern.** ATAK's override of her message icon.
    - **Open.** Drop the `.thm` sidecars.
11. **New activities and locations.** Survey positions in game, add anchors, add multi-point routines, tune slot weights.

## Backlog

Known issues outside the numbered steps.

- **Missing logic file for `squad_sleeping_gigant`.** `squad_descr_z_misc_encounter.ltx` sets `redux_logic = scripts\misc_encounter\squad_sleeping_gigant.ltx`, and that file is not in the repo or its history. Nothing in the repo spawns the squad. If something does, `load_storage_squad` logs the missing file and the squad runs without Redux logic. Either add the logic file or remove the squad definition.

## Open questions

- [x] Does the first `pt` field hold a wait time, and do points chain? Yes. Milliseconds, and `pt1..ptN` always loop. See Code findings.
- [x] Is `pos:` validated against the nav mesh? No, nowhere. Redux adds validation.
- [x] Are 18:00 to 19:00 and 23:00 to 24:00 uncovered? Yes, and 05:00 to 06:00 as well. All three fall to `logic@idle`.
- [x] Can Anna take Rostok smart terrain jobs? No. `smart_terrain_ex` skips any squad with the `redux_logic` key, so terrain jobs never reassign her and she never joins them.
- [ ] Which character\_desc file should DXML target for Anna's profile? DXML hooks character init directly, so a dedicated patch may need no host file at all.
- [ ] Are the surge shelters swapped? By day she goes from the gate to the far shelter near the bar, and by night the reverse. Inferred from coordinates, to test in game.
- [ ] After a quest kill, does idle inheritance jump her back to the hide spot with `meet = no_meet`, blocking the reward dialog? Inferred for all three combat quests, to test in game.
- [ ] How does `on_info` switching inside a beh section behave, and what clears the logic cache on level change? Not yet traced. Needed before steps 5 and 9.
- [ ] Logic switches clear animations immediately (`fast_set`), so leaving sleep or a seated pose pops. Is a softer exit worth building?
- [ ] Does the +0.5 y offset in vertex lookup pick the wrong floor on stacked geometry, such as the bunker?
- [ ] How should the current dev playthrough be versioned: treated as Redux version 0, or as pre-Redux?
- [ ] Removal policy: support uninstall from a live save, or document that it is unsupported?
- [ ] Rain variants in the first release, or deferred?

## Sources

- [xray-monolith repository](https://github.com/themrdemonized/xray-monolith)
- [xray-monolith releases](https://github.com/themrdemonized/xray-monolith/releases)
- [Extended scripting features (DeepWiki)](https://deepwiki.com/themrdemonized/xray-monolith/8.5-extended-scripting-features)

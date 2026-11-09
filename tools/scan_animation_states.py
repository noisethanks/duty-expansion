#!/usr/bin/env python3
"""Check every animation state used by this repo's LTX against two sources.

Sources:
  base   unpacked Anomaly scripts and meshes only
  gamma  the active MO2 profile: overwrite, then enabled mods in modlist order, then base

For each state the script resolves state_lib -> state_mgr_animation_list and
state_mgr_animstate_list -> motion names, and checks that every motion exists in
the union of the omf files Anna's model references. A state passes only if it
resolves in both sources.

Run from the repo root (read-only, Python 3 standard library only):
  python3 -I tools/scan_animation_states.py
Exit code 0 means every state resolves in both sources, 1 means at least one does not.
Run with --help for path options.
"""

import argparse
import os
import re
import struct
import sys
from collections import defaultdict

HOME = os.path.expanduser("~")
DEFAULT_BASE = os.path.join(HOME, "gamma/anomaly/tools/_unpacked")
DEFAULT_GAMMA = os.path.join(HOME, "gamma/gamma")
DEFAULT_PROFILE = "AlifePlusandQuests"
# The omf files duty_girl.ogf references. Checked with ogf string extraction.
DEFAULT_OMFS = [
    "stalker_animation",
    "stalker_scripts_animation",
    "stalker_smart_cover_animation",
    "stalker_scenario_animation",
]

SIT_ALL = ["animpoint_sit", "animpoint_sit_ass", "animpoint_sit_knee"]
# check_state_exception in xr_animpoint_predicates: these words need to appear in the pt string.
EXCEPTION_WORDS = ["guitar", "harmonica", "roast", "weapon"]
# Keys of an animation list sub-table that are actions, not motions.
# a/d attach/detach an item section, s plays a sound, sh hits, f calls a function.
ACTION_KEYS = {"a", "d", "s", "sh", "f"}
MUTANT_KEY = re.compile(r"redux_.*_animation")

SCRIPT_TABLES = {
    "states": [("scripts/state_lib.script", "states"), ("scripts/state_lib_animpoint.script", "return")],
    "animations": [
        ("scripts/state_mgr_animation_list.script", "animations"),
        ("scripts/state_mgr_animation_list_animpoint.script", "return"),
    ],
    "animstates": [
        ("scripts/state_mgr_animstate_list.script", "animations"),
        ("scripts/state_mgr_animstate_list_animpoint.script", "return"),
    ],
}
PREDICATES = "scripts/xr_animpoint_predicates.script"
RUNTIME_WRITE = re.compile(
    r"(state_lib\.states|state_mgr_animation_list\.animations|state_mgr_animstate_list\.animations)\s*\["
)

TOKEN = re.compile(
    r"""\s+|--\[\[.*?\]\]|--[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|-?\d+\.?\d*(?:[eE][-+]?\d+)?|[A-Za-z_][A-Za-z_0-9.]*|\.\.|[{}\[\](),=;:+\-*/<>~#%^]""",
    re.S,
)


# ---------------------------------------------------------------- Lua table parser


def tokenize(text):
    pos, out = 0, []
    while pos < len(text):
        m = TOKEN.match(text, pos)
        if not m:
            pos += 1
            continue
        t = m.group(0)
        pos = m.end()
        if t.isspace() or t.startswith("--"):
            continue
        out.append(t)
    return out


class Parser:
    def __init__(self, toks):
        self.t, self.i = toks, 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self):
        v = self.t[self.i]
        self.i += 1
        return v

    def value(self):
        t = self.peek()
        if t == "{":
            return self.table()
        if t and t[0] in "\"'":
            self.take()
            v = t[1:-1]
            if self.peek() == "..":
                while self.peek() not in (",", "}", ";", None):
                    self.take()
                return ("expr", v)
            return v
        depth, buf = 0, []
        while self.peek() is not None:
            p = self.peek()
            if depth == 0 and p in (",", "}", ";"):
                break
            if p in "([{":
                depth += 1
            if p in ")]}":
                depth -= 1
            buf.append(self.take())
        return ("expr", " ".join(buf))

    def table(self):
        assert self.take() == "{"
        d, pos = {}, 1
        while self.peek() not in ("}", None):
            if self.peek() in (",", ";"):
                self.take()
                continue
            if self.peek() == "[":
                self.take()
                kt = self.take()
                k = kt[1:-1] if kt[0] in "\"'" else kt
                while self.peek() != "]":
                    self.take()
                self.take()
                self.take()
                d[k] = self.value()
                continue
            nxt = self.t[self.i + 1] if self.i + 1 < len(self.t) else None
            if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", self.peek() or "") and nxt == "=":
                k = self.take()
                self.take()
                d[k] = self.value()
                continue
            d[str(pos)] = self.value()
            pos += 1
        if self.peek() == "}":
            self.take()
        return d


def motion_names(node):
    """Strings in an animation list entry that name motions. Skips prop and action tables."""
    out = []
    if isinstance(node, str):
        out.append(node)
    elif isinstance(node, dict):
        if node and set(node) <= ACTION_KEYS:
            return out
        for k, v in node.items():
            if k != "prop":
                out.extend(motion_names(v))
    return out


# ---------------------------------------------------------------- Sources


def read_omf(path, cache={}):
    if path in cache:
        return cache[path]
    data = open(path, "rb").read()
    names, pos = set(), 0
    while pos + 8 <= len(data):
        cid, size = struct.unpack_from("<II", data, pos)
        body = pos + 8
        if (cid & 0x7FFFFFFF) == 14:  # OGF_S_MOTIONS
            sp, end = body, body + size
            while sp + 8 <= end:
                sid, ssz = struct.unpack_from("<II", data, sp)
                if sid >= 1:
                    raw = data[sp + 8 : sp + 8 + min(ssz, 128)]
                    nm = raw.split(b"\x00", 1)[0].decode("latin-1")
                    if nm:
                        names.add(nm.lower())
                sp += 8 + ssz
        pos = body + size
    cache[path] = names
    return names


class Source:
    def __init__(self, name, layers, omfs):
        self.name = name
        self.layers = layers  # [(root_dir, prefix)] highest priority first
        self.files = {}
        self.tables = {}
        self.sources = []
        for key, specs in SCRIPT_TABLES.items():
            merged = {}
            for rel, var in specs:
                path = self.find(rel)
                merged.update(self.load_table(path, var))
                self.sources.append(path)
            self.tables[key] = merged
        self.pred_path = self.find(PREDICATES)
        self.omf_paths = [self.find("meshes/actors/%s.omf" % n) for n in omfs]
        self.motions = set()
        for p in self.omf_paths:
            self.motions |= read_omf(p)

    def find(self, rel):
        if rel in self.files:
            return self.files[rel]
        for root, prefix in self.layers:
            p = os.path.join(root, prefix, rel)
            if os.path.exists(p):
                self.files[rel] = p
                return p
        raise SystemExit("%s: %s not found in any layer" % (self.name, rel))

    @staticmethod
    def load_table(path, varname):
        toks = tokenize(open(path, "r", encoding="latin-1").read())
        for i in range(len(toks) - 2):
            if varname == "return" and toks[i] == "return" and toks[i + 1] == "{":
                return Parser(toks[i + 1 :]).table()
            if toks[i] == varname and toks[i + 1] == "=" and toks[i + 2] == "{":
                return Parser(toks[i + 2 :]).table()
        raise SystemExit("no %s table in %s" % (varname, path))

    def associations(self, base):
        names, inside = [], False
        for ln in open(self.pred_path, encoding="latin-1"):
            s = ln.strip()
            if not inside:
                if re.match(r"^%s\s*=\s*\{" % re.escape(base), s):
                    inside = True
                else:
                    continue
            if s.startswith("--"):
                continue
            names += re.findall(r'\{\s*name\s*=\s*"([^"]+)"', s)
            if s.startswith("}") or (s.endswith("},") and "name" not in s):
                break
        return names

    def expand(self, name):
        """State names the framework can pick for a pt value."""
        if "@random" not in name:
            return [name]
        base = name.split("@")[0]
        bases = SIT_ALL if base == "animpoint_sit_all" else [base]
        out = []
        for b in bases:
            for n in self.associations(b):
                if all((w not in n) or (w in name) for w in EXCEPTION_WORDS):
                    out.append(n)
        return out

    def check(self, state):
        """Return (status, detail). Status is ok, undefined or missing."""
        st = self.tables["states"].get(state)
        if st is None:
            return "undefined", "not in state_lib"
        need = []
        for field, table in (("animation", "animations"), ("animstate", "animstates")):
            ref = st.get(field) if isinstance(st, dict) else None
            if not isinstance(ref, str):
                continue
            entry = self.tables[table].get(ref)
            if entry is None:
                return "undefined", "no %s entry %s" % (table, ref)
            need += motion_names(entry)
        missing = sorted({m for m in need if m.lower() not in self.motions})
        return ("missing", ", ".join(missing)) if missing else ("ok", "")

    def runtime_writers(self, mod_roots):
        hits = []
        for root in mod_roots:
            sdir = os.path.join(root, "scripts")
            if not os.path.isdir(sdir):
                continue
            for fn in os.listdir(sdir):
                if fn.endswith(".script"):
                    p = os.path.join(sdir, fn)
                    if RUNTIME_WRITE.search(open(p, "r", encoding="latin-1").read()):
                        hits.append(p)
        return hits


def gamma_layers(gamma_dir, profile):
    layers = [(os.path.join(gamma_dir, "overwrite"), "gamedata")]
    enabled = []
    modlist = os.path.join(gamma_dir, "profiles", profile, "modlist.txt")
    # MO2 writes modlist.txt with the highest priority mod first.
    for line in open(modlist, encoding="utf-8", errors="replace"):
        line = line.rstrip("\r\n")
        if line.startswith("+"):
            enabled.append(line[1:])
    for name in enabled:
        layers.append((os.path.join(gamma_dir, "mods", name), "gamedata"))
    return layers, enabled


# ---------------------------------------------------------------- Repo scan

KEY = re.compile(r"^\s*([A-Za-z_0-9@]*)\s*=\s*(.*?)\s*$")
SECT = re.compile(r"^\s*\[([^\]]+)\]")


def scan_repo(repo):
    """Return {state: [(use, is_mutant_key)]} for every state name in the repo's LTX."""
    uses = defaultdict(list)
    root = os.path.join(repo, "gamedata")

    def add(state, path, ln, section, key):
        state = state.strip()
        if state and state not in ("nil", "true", "false"):
            uses[state].append(("%s:%d [%s] %s" % (os.path.relpath(path, repo), ln, section, key), bool(MUTANT_KEY.fullmatch(key))))

    for dp, _, fns in os.walk(root):
        for fn in sorted(fns):
            if not fn.endswith(".ltx"):
                continue
            p = os.path.join(dp, fn)
            section = ""
            with open(p, "r", encoding="utf-8-sig", errors="replace") as fh:
                for ln, line in enumerate(fh, 1):
                    line = line.split(";")[0].rstrip("\r\n")
                    m = SECT.match(line)
                    if m:
                        section = m.group(1)
                        continue
                    m = KEY.match(line)
                    if not m:
                        continue
                    key, val = m.group(1), m.group(2)
                    if re.fullmatch(r"pt\d*", key):
                        fields = [f.strip() for f in val.split("|")[0].split(",")]
                        if len(fields) > 1 and not fields[0].startswith("pos:"):
                            add(fields[1], p, ln, section, key)
                    elif re.search(r"(anim|animation|state)", key) and key != "redux_logic":
                        v = re.sub(r"%[^%]*%", "", re.sub(r"\{[^}]*\}", "", val))
                        for part in v.split(","):
                            add(part, p, ln, section, key)
    return uses


# ---------------------------------------------------------------- Main


def category(base_status, gamma_status):
    fail_b, fail_g = base_status[0] != "ok", gamma_status[0] != "ok"
    if base_status[0] == "undefined" and gamma_status[0] == "undefined":
        return "UNDEFINED"
    if fail_b and fail_g:
        return "BOTH"
    if fail_b:
        return "BASE-ONLY"
    if fail_g:
        return "GAMMA-ONLY"
    return "OK"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--base", default=DEFAULT_BASE, help="unpacked Anomaly dir (contains scripts/ and meshes/)")
    ap.add_argument("--gamma", default=DEFAULT_GAMMA, help="MO2 instance dir (contains mods/, overwrite/, profiles/)")
    ap.add_argument("--profile", default=DEFAULT_PROFILE)
    ap.add_argument("--omf", action="append", help="omf basename without extension, repeatable")
    ap.add_argument("--all", action="store_true", help="print passing states too")
    args = ap.parse_args()
    omfs = args.omf or DEFAULT_OMFS

    base_layers = [(args.base, "")]
    layers, enabled = gamma_layers(args.gamma, args.profile)
    base = Source("base", base_layers, omfs)
    gamma = Source("gamma", layers + base_layers, omfs)

    print("base : %d motions in %s" % (len(base.motions), ", ".join(os.path.basename(p) for p in base.omf_paths)))
    print("gamma: %d motions, profile %s, %d enabled mods" % (len(gamma.motions), args.profile, len(enabled)))
    for p in gamma.omf_paths:
        print("  wins: %s" % os.path.relpath(p, args.gamma))
    for p in sorted({p for p in gamma.sources + [gamma.pred_path] if p not in base.sources + [base.pred_path]}):
        print("  script differs from base: %s" % os.path.relpath(p, args.gamma))
    writers = gamma.runtime_writers([os.path.join(r, pre) for r, pre in layers])
    for p in writers:
        print("  WARNING runtime table write, not parsed: %s" % os.path.relpath(p, args.gamma))
    print()

    uses = scan_repo(args.repo)
    rows, mutant_only = [], []
    for raw, entries in sorted(uses.items()):
        if all(m for _, m in entries):
            mutant_only.append(raw)
            continue
        where = entries[0][0] + (" (+%d)" % (len(entries) - 1) if len(entries) > 1 else "")
        finals = gamma.expand(raw)
        if not finals:
            rows.append((raw, "UNDEFINED", ("undefined", "no associations"), ("undefined", "no associations"), where))
            continue
        for name in finals:
            b, g = base.check(name), gamma.check(name)
            rows.append((name, category(b, g), b, g, where))

    seen, final_rows = set(), []
    for r in rows:
        if r[0] not in seen:
            seen.add(r[0])
            final_rows.append(r)
    bad = [r for r in final_rows if r[1] != "OK"]
    show = final_rows if args.all else bad

    def cell(s):
        return s[0] if s[0] == "ok" else "%s: %s" % s

    print("state\tcategory\tbase\tgamma\tused where")
    for name, cat, b, g, where in sorted(show, key=lambda r: (r[1], r[0])):
        print("%s\t%s\t%s\t%s\t%s" % (name, cat, cell(b), cell(g), where))
    print()
    print("%d states checked, %d fail in at least one source, %d mutant animation names skipped" % (len(final_rows), len(bad), len(mutant_only)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

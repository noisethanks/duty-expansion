-- Offline harness for the anchor resolver in duty_redux_logic.script.
-- Stubs the engine (level graph, vectors, ini files) and checks resolve_point and debug_anchors.
--
-- Run from the repo root:
--   lua5.1 tools/anchor_harness.lua
-- Optional arguments override the script and anchor file paths:
--   lua5.1 tools/anchor_harness.lua <duty_redux_logic.script> <anchors.ltx>

local script_path = arg[1] or "gamedata/scripts/duty_redux_logic.script"
local anchor_path = arg[2] or "gamedata/configs/scripts/duty_redux/anchors.ltx"

-- Tables that create empty sub-tables on access, for globals the script touches at load time.
local function auto()
    return setmetatable({}, {
        __index = function(t, k)
            local v = auto()
            rawset(t, k, v)
            return v
        end,
    })
end

local env = setmetatable({}, { __index = _G })
for _, n in ipairs({
    "xr_conditions",
    "xr_effects",
    "xr_combat_ignore",
    "xr_combat_camper",
    "state_lib",
    "utils_obj",
    "axr_companions",
    "db",
    "move",
    "anim",
    "look",
    "cond",
    "clsid",
    "game_object",
    "CSightParams",
    "xr_logic",
}) do
    env[n] = auto()
end
env.copy_table = function() end

local logged = {}
env.printf = function(fmt, ...)
    local s = string.format(fmt, ...)
    logged[#logged + 1] = s
    print("  LOG " .. s)
end

local V = {}
V.__index = V
function V:set(x, y, z)
    if type(x) == "table" then
        x, y, z = x.x, x.y, x.z
    end
    self.x, self.y, self.z = x, y, z
    return self
end
function V:normalize()
    local l = math.sqrt(self.x ^ 2 + self.y ^ 2 + self.z ^ 2)
    return self:set(self.x / l, self.y / l, self.z / l)
end
env.vector = function() return setmetatable({ x = 0, y = 0, z = 0 }, V) end
env.vector_rotate_y = function(v, a)
    local r = math.rad(a)
    return env.vector():set(v.x * math.cos(r) + v.z * math.sin(r), v.y, -v.x * math.sin(r) + v.z * math.cos(r))
end
env.str_explode = function(s, sep)
    local t = {}
    for p in (s .. sep):gmatch("(.-)" .. sep) do
        t[#t + 1] = p:match("^%s*(.-)%s*$")
    end
    return t
end

-- Nav mesh stub: positions with |x| and |z| below 500 are on the mesh, everything else is invalid.
local current_level = "l05_bar"
local vertex_calls = {}
env.level = {
    name = function() return current_level end,
    vertex_id = function(p)
        vertex_calls[#vertex_calls + 1] = { x = p.x, y = p.y, z = p.z }
        if math.abs(p.x) < 500 and math.abs(p.z) < 500 then return math.floor(p.x) * 1000 + math.floor(p.z) + 500000 end
        return 4294967295
    end,
    vertex_position = function() return env.vector():set(1, 2, 3) end,
}

-- Minimal ini reader with the calls the script uses.
local function read_ini(path)
    local secs, order, cur = {}, {}, nil
    for line in io.lines(path) do
        line = line:gsub("\r", ""):gsub(";.*", "")
        local s = line:match("^%[([^%]]+)%]")
        if s then
            cur = s
            secs[s], order[s] = {}, {}
        elseif cur then
            local k, v = line:match("^%s*([^=%s]+)%s*=%s*(.-)%s*$")
            if k then
                secs[cur][k] = v
                table.insert(order[cur], k)
            end
        end
    end
    return {
        section_exist = function(_, s) return secs[s] ~= nil end,
        line_count = function(_, s) return #order[s] end,
        r_line = function(_, s, i)
            local k = order[s][i + 1]
            return true, k, secs[s][k]
        end,
    }
end
env.ini_file = function(p)
    if p == "scripts\\duty_redux\\anchors.ltx" then return read_ini(anchor_path) end
end

local chunk = assert(loadfile(script_path))
setfenv(chunk, env)
chunk()

local function npc(accessible)
    return {
        id = function() return 7 end,
        name = function() return "anna" end,
        accessible = function(_, vid) return accessible(vid) end,
        accessible_nearest = function(_, _, out) return 42, out end,
        position = function() return env.vector():set(9, 9, 9) end,
        level_vertex_id = function() return 99 end,
    }
end
local function always() return true end
local function never() return false end

local failed = 0
local function check(label, ok)
    print((ok and "PASS " or "FAIL ") .. label)
    if not ok then failed = failed + 1 end
end

local resolve = env.resolve_point

local p, vid, yaw, how = resolve(npc(always), "999999,guard | anchor:bar_gate", "beh@guard", "pt1", true)
check(
    "anchor resolves to its exact position and yaw",
    p.x == 85.4 and p.y == 0.0 and p.z == 137.9 and yaw == 90 and how == "ok"
)
check("vertex lookup keeps the +0.5 y offset", vertex_calls[1].y == 0.5)

local p2, vid2, _, how2 = resolve(npc(always), "999999,guard | pos:85.4,0.0,137.9 dir:90", "beh@guard", "pt1", true)
check("raw pos: gives the same result as the anchor", p2.x == p.x and p2.z == p.z and vid2 == vid and how2 == "ok")

local p3, _, yaw3 = resolve(npc(always), "999999,sit | anchor:bar_campfire animpoint:pos", "beh@drink", "pt1", true)
check("bar_campfire with animpoint:pos", p3.x == 207.9 and p3.z == 85.4 and yaw3 == 135)

local _, v4, _, h4 = resolve(npc(never), "x | anchor:bar_gate", "s", "pt1", true)
check("inaccessible anchor falls back to nearest accessible vertex", v4 == 42 and h4 == "nearest")

local p5, v5, _, h5 = resolve(npc(always), "x | anchor:nope", "s", "pt1", true)
check("unknown anchor stands at current vertex", v5 == 99 and h5 == "current" and p5.x == 9)

local _, v6, _, h6 = resolve(npc(always), "x | pos:9000,0,9000", "s", "pt2", true)
check("off-mesh raw pos: stands at current vertex", v6 == 99 and h6 == "current")

local p7 = resolve(npc(always), "x | anchor:bar_gate pos:1,1,1", "s", "pt3", true)
check("anchor: wins over pos: on the same line", p7.x == 85.4)

check("line with no anchor: or pos: returns nil", resolve(npc(always), "x | dir:90", "s", "pt4", true) == nil)

local called = false
local _, _, _, h8 = resolve(
    npc(function()
        called = true
        return false
    end),
    "x | anchor:bar_gate",
    "s",
    "pt1",
    false
)
check("net spawn skips npc:accessible", h8 == "ok" and not called)

local before = #logged
resolve(npc(always), "x | anchor:nope", "s", "pt1", true)
resolve(npc(always), "x | pos:9000,0,9000", "s", "pt2", true)
check("repeat failures are not logged again", #logged == before)

current_level = "l02_garbage"
local n = #vertex_calls
local _, _, _, h9 = resolve(npc(always), "x | anchor:bar_gate", "s", "pt1", true)
check("another level never looks up Rostok coordinates", #vertex_calls == n and h9 == "current")

current_level = "l05_bar"
env.debug_anchors()

if failed > 0 then
    print(failed .. " FAILED")
    os.exit(1)
end
print("ALL PASS")

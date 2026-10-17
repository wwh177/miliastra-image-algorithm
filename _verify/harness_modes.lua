local function I(v) return math.floor(tonumber(v) or 0) end
-- ---- 查表 ----
local HEXV = {}
for i = 0, 9 do HEXV[48 + i] = i end
for i = 0, 5 do HEXV[65 + i] = 10 + i; HEXV[97 + i] = 10 + i end
local B64V = {}
do
    local CH = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    for i = 1, #CH do B64V[string.byte(CH, i)] = i - 1 end
end

-- ---- 扫描推演 ----
local function newScan(N) return { occ = {}, ci = 0, cj = 0, N = N } end

local function scanNext(S)
    while true do
        while S.ci < S.N do
            local o = S.occ[S.ci]
            if o and o >= S.cj then S.ci = S.ci + 1 else break end
        end
        if S.ci < S.N then return S.ci, S.cj end
        S.cj = S.cj + 1
        S.ci = 0
    end
end

local function scanPlace(S, x, y, w, h)
    local last = y + h - 1
    for xx = x, x + w - 1 do
        local o = S.occ[xx]
        if not o or o < last then S.occ[xx] = last end
    end
    S.ci = x + w
end

-- ---- 解码器 ----
local function makeDecoder(enc, data, N)
    local S = newScan(N)
    if enc == "b64" then
        return function(i)
            local base = (i - 1) * 7
            local c1, c2, c3, c4, c5, c6, c7 = string.byte(data, base + 1, base + 7)
            if not c7 then return nil end
            local v1, v2, v3, v4 = B64V[c1], B64V[c2], B64V[c3], B64V[c4]
            local v5, v6, v7 = B64V[c5], B64V[c6], B64V[c7]
            if not (v1 and v2 and v3 and v4 and v5 and v6 and v7) then return nil end
            local a = ((v1 * 64 + v2) * 64 + v3) * 64 + v4     -- < 2^24，32 位安全
            local w = math.floor(a / 65536)
            local h = math.floor(a / 256) % 256
            local r = a % 256
            local b2 = (v5 * 64 + v6) * 64 + v7                 -- < 2^18
            local g = math.floor(b2 / 256)
            local b = b2 % 256
            local x, y = scanNext(S)
            scanPlace(S, x, y, w, h)
            return x, y, w, h, r, g, b
        end
    end
    return function(i)
        local o = (i - 1) * 10
        local a1, a2, a3, a4, a5, a6, a7, a8, a9, a10 =
            string.byte(data, o + 1, o + 10)
        if not a10 then return nil end
        local w = HEXV[a1] * 16 + HEXV[a2]
        local h = HEXV[a3] * 16 + HEXV[a4]
        local r = HEXV[a5] * 16 + HEXV[a6]
        local g = HEXV[a7] * 16 + HEXV[a8]
        local b = HEXV[a9] * 16 + HEXV[a10]
        local x, y = scanNext(S)
        scanPlace(S, x, y, w, h)
        return x, y, w, h, r, g, b
    end
end



local MOD = 16777216
local function roll(h, b) return (h * 131 + b) % MOD end
for mi = 1, #MD.MODES do
    local m = MD.MODES[mi]
    local N = m.src or MD.N
    local dec = makeDecoder(m.enc or "hex", m.data, N)
    local chk, n, area = 0, 0, 0
    for i = 1, m.n do
        local x, y, w, h, r, g, b = dec(i)
        if not x then break end
        n = n + 1
        area = area + w * h
        chk = roll(chk, x); chk = roll(chk, y); chk = roll(chk, w)
        chk = roll(chk, h); chk = roll(chk, r); chk = roll(chk, g); chk = roll(chk, b)
    end
    print(string.format("MODE %d src=%d n=%d chk=%d area=%d/%d", mi, N, n, chk, area, N*N))
end

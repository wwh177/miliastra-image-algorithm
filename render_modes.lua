-- ============================================================================
--  render_modes.lua —— 多档切换渲染器（配套 pack_modes.py）
--                     用于对比不同 STD / 分辨率的画质与控件数
-- ============================================================================
--
--  【用途】
--    把 pack_modes.py 打包的多档数据渲染出来，按 P 键实时切换档位，
--    直接在游戏里对比画质差异与控件数代价。
--
--  【怎么用】
--    1) python pack_modes.py --input 图.png --specs 256:1,200:0 --out cmp.lua --preview
--    2) python assemble_modes.py cmp.lua render_modes.lua 输出.lua
--    3) 把 输出.lua 部署到关卡，进关卡按 P 切换
--
--  【数据格式】（pack_modes.py 生成）
--    MD.POOL   控件池大小（= 各档最大块数）
--    MD.BITS   每通道位数
--    MD.MODES  { {std, src, n, enc, mae, data}, ... }
--      src  = 该档源分辨率；enc = "b64"|"hex"；n = 块数；data = 编码后的块数据
--    ★ 坐标 x,y 不存储：块按"行主序扫描顺序"排列，解码端重放扫描还原
--
--  【显示策略】
--    RENDER.UNIT = "AUTO" 时，**所有档位显示为同一屏幕尺寸**（便于公平对比）
--
--  【性能须知（实测）】
--    新建控件 ≈ 0.223 ms/个；改属性 ≈ 0.004 ms/次（快 50 倍）
--    切换只改属性、绝不销毁重建（在事件回调里大量销毁会触发引擎销毁脚本）
--    实测 50,000 控件正常；61,440 崩溃
-- ============================================================================


-- ============================================================================
-- ▼▼▼ 数据区：把 pack_modes.py 的输出整段替换到这里 ▼▼▼
-- ============================================================================
local MD = {}
MD.POOL = 0
MD.BITS = 8
MD.N = 4
MD.MODES = {}
-- ============================================================================
-- ▲▲▲ 数据区结束 ▲▲▲
-- ============================================================================


-- ============================================================================
-- RENDER 区（可调参数）
-- ============================================================================
local RENDER = {
    TEMPLATE = 0,                                   -- 0 = 自动探测
    TEMPLATE_PRIORITY = { 1073741931, 1073758498, 1073741926 },
    TEMPLATE_SCAN = { 1073741800, 1073742100 },
    UNIT = "AUTO",          -- "AUTO" = 各档统一屏幕尺寸；数字 = 固定 UNIT
    MAX_RATIO = 0.98,       -- 图最多占画布的比例
    MARGIN_PX = 0.20,       -- ★ 每块向外扩多少【源像素】（防拼缝）。必须与分辨率挂钩！
    MARGIN = nil,           -- 兼容旧配置：填了就用它（画布单位，绝对值，高分辨率下会过度外扩）
    RECT_IMG = 100001,
    SHOW_CURSOR = true,
    LOCK_CHARACTER = true,
    SWITCH_KEY = "KeyboardCraftspersonKey18Down",   -- P 键
    SHOW_TEXT = true,       -- 是否显示顶部提示文字
}


-- ============================================================================
-- 实现
-- ============================================================================
local function log(...) print("[modes] " .. table.concat({ ... }, " ")) end
local function err(...) printerr("[modes] " .. table.concat({ ... }, " ")) end
local function I(v) return math.floor(tonumber(v) or 0) end

local host, template = nil, 0
local canvasW, canvasH = 0, 0
local pool = {}
local modeIdx = 1
local pendingSwitch = false
local busy = false
local ctlMsg = nil
local TXT_TEMPLATE = nil

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

-- ---- 模板 ----
local function tryTemplate(id)
    local ok, c = pcall(game.InstantiateClientUIControl, id, host)
    if ok and c ~= nil then
        local isImg = pcall(function()
            c.SetImage(c, Enum.ImageSource.StaticReference, RENDER.RECT_IMG)
        end)
        pcall(game.DestroyClientUIControl, c)
        if isImg then return id end
    end
    return nil
end

local function discoverTemplate()
    if RENDER.TEMPLATE and RENDER.TEMPLATE > 0 then
        local t = tryTemplate(RENDER.TEMPLATE)
        if t then return t end
    end
    for i = 1, #RENDER.TEMPLATE_PRIORITY do
        local t = tryTemplate(RENDER.TEMPLATE_PRIORITY[i])
        if t then log("模板命中优先项 " .. I(t)) return t end
    end
    for id = RENDER.TEMPLATE_SCAN[1], RENDER.TEMPLATE_SCAN[2] do
        local t = tryTemplate(id)
        if t then log("模板自动探测命中 " .. I(t)) return t end
    end
    return nil
end

local function discoverTextBox()
    for id = RENDER.TEMPLATE_SCAN[1], RENDER.TEMPLATE_SCAN[2] do
        local ok, c = pcall(game.InstantiateClientUIControl, id, host)
        if ok and c ~= nil then
            local cls = tostring(c)
            pcall(game.DestroyClientUIControl, c)
            if string.find(cls, "TextBox", 1, true) then return id end
        end
    end
    return nil
end

local function newRect(x, y, w, h, r, g, b)
    local c = game.InstantiateClientUIControl(template, host)
    if c == nil then return nil end
    c:SetAnchorMin(0.5, 0.5) c:SetAnchorMax(0.5, 0.5) c:SetPivot(0.5, 0.5)
    c:SetSizeDelta(w, h)
    c.SetImage(c, Enum.ImageSource.StaticReference, RENDER.RECT_IMG)
    c.imageType = Enum.ImageType.Stretch
    c.imageColor = Color.FromRGBA(r, g, b, 255)
    c:SetAnchoredPosition(x, y)
    return c
end

-- 计算某档的 UNIT 与显示边长
local function unitFor(srcN)
    srcN = math.max(1, srcN)
    local limit = math.min(canvasW, canvasH) * RENDER.MAX_RATIO
    local u = RENDER.UNIT
    if type(u) == "string" then
        return limit / srcN, limit
    end
    local need = srcN * u
    if need > limit then
        local fit = limit / srcN
        log(string.format("UNIT %.3f 超出画布，自动改为 %.3f", u, fit))
        return fit, limit
    end
    return u, need
end

-- ---- 显示某档 ----
local function showMode(idx)
    local m = MD.MODES[idx]
    if not m then err("档位 " .. I(idx) .. " 不存在") return end
    local srcN = m.src or MD.N
    local unit, side = unitFor(srcN)
    -- ★ 外扩量必须跟分辨率挂钩（详见 render.lua 同名改动）。
    --   固定 1 画布单位在 800x800 下等于每边外扩 0.91 源像素，而 66% 的块是 1x1，
    --   会被画成约 2.8x2.8 → 规律性毛边。口径改成"源像素"后与分辨率、画布无关。
    local mg = RENDER.MARGIN
    if mg == nil then mg = (RENDER.MARGIN_PX or 0.20) * unit end
    local t0 = os.clock()
    local dec = makeDecoder(m.enc or "hex", m.data, srcN)
    local made = 0

    for i = 1, m.n do
        local x, y, w, h, r, g, b = dec(i)
        if not x then break end
        local c = pool[i]
        if not c then break end
        c:SetSizeDelta(w * unit + mg * 2, h * unit + mg * 2)
        c:SetAnchoredPosition(
            -side * 0.5 + (x + w * 0.5) * unit,
            side * 0.5 - (y + h * 0.5) * unit)
        c.imageColor = Color.FromRGBA(r, g, b, 255)
        made = i
    end

    -- 多余控件隐藏：尺寸归零 + 移出画布（避免大量 SetVisible 调用）
    for k = made + 1, #pool do
        local c = pool[k]
        c:SetSizeDelta(0, 0)
        c:SetAnchoredPosition(99999, 99999)
    end

    log(string.format(
        "★ 档位 %d/%d：%dx%d STD=%s  块数 %d  MAE=%.2f  编码=%s  UNIT=%.3f  显示 %.0f 单位  占用 %d/%d  切换 %.2f s",
        idx, #MD.MODES, srcN, srcN, tostring(m.std), m.n, m.mae or 0,
        tostring(m.enc), unit, side, made, I(#pool), os.clock() - t0))
    if ctlMsg then
        pcall(function()
            ctlMsg.text = string.format("%dx%d  STD=%s  %d块  MAE=%.2f   (P 切换)",
                srcN, srcN, tostring(m.std), I(m.n), m.mae or 0)
        end)
    end
end

local function buildPool()
    local t0 = os.clock()
    for i = 1, MD.POOL do
        local c = game.InstantiateClientUIControl(template, host)
        if c == nil then break end
        c:SetAnchorMin(0.5, 0.5) c:SetAnchorMax(0.5, 0.5) c:SetPivot(0.5, 0.5)
        c:SetSizeDelta(0, 0)
        c.SetImage(c, Enum.ImageSource.StaticReference, RENDER.RECT_IMG)
        c.imageType = Enum.ImageType.Stretch
        c.imageColor = Color.FromRGBA(0, 0, 0, 255)
        c:SetAnchoredPosition(99999, 99999)
        pool[#pool + 1] = c
    end
    log(string.format("控件池 = %d 个（%.1f s）", I(#pool), os.clock() - t0))
end

function OnStart()
    log("===== 多档切换渲染器 =====")
    host = script.object
    pcall(function()
        local p = host and host.parent
        if p and p.alive then host = p end
    end)
    canvasW, canvasH = game.GetUICanvasSize()
    canvasW, canvasH = I(canvasW), I(canvasH)
    log(string.format("画布 %dx%d  宿主=%s", canvasW, canvasH, tostring(host)))

    if not MD.MODES or #MD.MODES == 0 then
        err("数据区为空：请把 pack_modes.py 的输出粘进本文件的『数据区』")
        return
    end

    template = discoverTemplate()
    if not template then
        err("找不到图片控件模板，请按 README 创建『客户端控件模板』")
        return
    end
    log("使用模板 = " .. I(template))

    local strs = {}
    for i = 1, #MD.MODES do
        local mm = MD.MODES[i]
        strs[#strs + 1] = string.format("%dpx/STD=%s(%d块,MAE%.2f,%s)",
            mm.src or MD.N, tostring(mm.std), I(mm.n), mm.mae or 0, tostring(mm.enc))
    end
    log(string.format("颜色 %d 位（%s）", MD.BITS,
        MD.BITS >= 8 and "24 位真彩，不量化" or "已量化"))
    log("档位：" .. table.concat(strs, "  |  "))
    log(string.format("控件池 = %d（各档最大块数）", I(MD.POOL)))
    if MD.POOL > 55000 then
        err(string.format("⚠️ 池 %d 偏大（实测 50,000 正常、61,440 崩溃）", I(MD.POOL)))
    end
    log(string.format("显示策略：%s（画布 %dx%d，上限比例 %.2f）",
        (type(RENDER.UNIT) == "string") and "各档统一屏幕尺寸（UNIT=AUTO）"
            or ("固定 UNIT=" .. tostring(RENDER.UNIT)),
        canvasW, canvasH, RENDER.MAX_RATIO))

    -- 白底板
    local bg = newRect(0, 0, canvasW, canvasH, 255, 255, 255)
    if bg then log("白底板已建立") end

    buildPool()

    -- 顶部提示文字
    if RENDER.SHOW_TEXT then
        TXT_TEMPLATE = discoverTextBox()
        if TXT_TEMPLATE then
            local ok, m = pcall(game.InstantiateClientUIControl, TXT_TEMPLATE, host)
            if ok and m then
                pcall(function() m:SetSizeDelta(1200, 70) end)
                pcall(function() m:SetAnchoredPosition(0, canvasH * 0.5 - 60) end)
                pcall(function() m.text = "加载中…" end)
                pcall(function() m.fontSize = 34 end)
                pcall(function() m.adaptiveFontSize = false end)
                pcall(function() m.fontColor = Color.FromRGBA(20, 20, 20, 255) end)
                pcall(function() m.bgColor = Color.FromRGBA(255, 255, 255, 0) end)
                ctlMsg = m
                log("提示文字模板 = " .. I(TXT_TEMPLATE))
            end
        end
    end

    showMode(1)

    -- 输入
    local t = script.object
    if RENDER.SHOW_CURSOR then pcall(function() t.showCursor = true end) end
    if RENDER.LOCK_CHARACTER then
        pcall(function() t.disableKeyEventPassthrough = true end)
    end
    local ev = Enum.KeyEventType[RENDER.SWITCH_KEY]
    if ev then
        pcall(function()
            t:AddKeyEventListener(ev, function()
                if not pendingSwitch and not busy then
                    pendingSwitch = true
                    log("★ P 键 → 请求切换档位")
                end
                return true
            end)
        end)
        log("P 键 = 切换档位")
    else
        err("找不到按键枚举 " .. RENDER.SWITCH_KEY)
    end

    pcall(function() script:EnableUpdate(true) end)
    log("===== 就绪：按 P 依次切换档位 =====")
end

function OnUpdate(dt)
    if pendingSwitch and not busy then
        pendingSwitch = false
        busy = true
        modeIdx = modeIdx % #MD.MODES + 1
        local ok, e = pcall(showMode, modeIdx)
        if not ok then err("切换出错: " .. tostring(e)) end
        busy = false
    end
end

function OnDestroy()
    log("[modes] OnDestroy")
    if host then
        pcall(function() host:RemoveAllKeyEventListeners() end)
        pcall(function() host:RemoveAllCursorEventListeners() end)
    end
end

-- ============================================================
--  03_pixel_render_min.lua —— 最小像素画渲染示例（可直接改成游戏）
--
--  演示：
--    · 一次性爆发创建 N×N 个控件（每个 = 1 个逻辑像素）
--    · 真彩上色（每控件只写一次颜色 → 无条纹）
--    · 正确的坐标与索引约定
--    · 硬校验数据长度
--    · 可重入（OnStart 先清理上一轮）
--    · showCursor / disableKeyEventPassthrough
--
--  用法：把 @@DATA@@ 替换成你的数据（见 tools/gen_pixels.py 的输出），
--        或先用内置的渐变数据测试（本文件默认就是渐变色，无需外部数据）
-- ============================================================

-- ---------- 配置 ----------
local PW       = 128          -- 像素网格边长（实测上限 200）
local CELL     = 6            -- 每个逻辑像素占多少画布单位
local OVERLAP  = 0.5          -- 每边外扩，消除相邻控件细缝
local RECT_IMG = 100001       -- 内置直角白图
local TPL_IMG  = 1073741931   -- ★ 模板 ID，失效时用 discoverTemplate 自动找

-- ---------- 数据（默认：内置渐变，便于直接测试）----------
-- 若要用真实图像，用 tools\gen_pixels.py 生成数据，替换下面这段：
--
--     local PIXEL = {}
--     PIXEL.PW  = 128
--     PIXEL.RGB = "<很长的 hex 串>"
--     local THUMB = {}
--     THUMB.TN  = 108
--     THUMB.RGB = "<很长的 hex 串>"
--
-- ★ 注：luacheck 会报「PIXEL / RGB 未声明」—— 这是**故意的**，
--   因为它们由外部数据段提供。若用内联数据，把上面三行写在文件顶部即可消除告警。

-- ---------- 日志 ----------
local function log(...) print("[px] " .. table.concat({ ... }, " ")) end
local function err(...) printerr("[px] " .. table.concat({ ... }, " ")) end
local function I(v) return math.floor(tonumber(v) or 0) end

-- ---------- 状态 ----------
local host, W, H = nil, 0, 0
local CREATED = {}
local flat = {}

-- ---------- 模板自动探测（模板 ID 变了也能自适应）----------
local function discoverTemplate(wantClass)
    local prio = { 1073741931, 1073741926, 1073758498, 1073758497 }
    local function test(id)
        local ok, c = pcall(game.InstantiateClientUIControl, id, host)
        if ok and c ~= nil then
            local cls = tostring(c)
            pcall(game.DestroyClientUIControl, c)
            if not wantClass or string.find(cls, wantClass, 1, true) then
                return true, cls
            end
        end
        return false
    end
    for i = 1, #prio do
        local f, cls = test(prio[i]); if f then return prio[i], cls, "候选" end
    end
    local ranges = { {1073741800, 1073742100}, {1073758300, 1073759000} }
    for r = 1, #ranges do
        for id = ranges[r][1], ranges[r][2] do
            local f, cls = test(id); if f then return id, cls, "扫描" end
        end
    end
    return nil, nil, "失败"
end

-- ---------- 解包真彩 RLE（含硬校验）----------
local function unpackTruecolor(hex, expect)
    local raw = (hex:gsub('%x%x', function(cc) return string.char(tonumber(cc, 16)) end))
    local out, n, i, len = {}, 0, 1, #raw
    while i + 3 <= len do
        local r, g, b, run = string.byte(raw, i), string.byte(raw, i+1),
                             string.byte(raw, i+2), string.byte(raw, i+3)
        for _ = 1, run do n = n + 1; out[n] = { r, g, b } end
        i = i + 4
    end
    if expect and n ~= expect then
        err(string.format("解包长度 %d != 期望 %d", n, expect))
    end
    return out
end

-- ---------- 建一个色块 ----------
local function newBlock(color, size)
    local ctl = game.InstantiateClientUIControl(TPL_IMG, host)
    if ctl == nil then return nil end
    pcall(function() ctl:SetAnchorMin(0.5, 0.5) end)
    pcall(function() ctl:SetAnchorMax(0.5, 0.5) end)
    pcall(function() ctl:SetPivot(0.5, 0.5) end)
    pcall(function() ctl:SetSizeDelta(size + OVERLAP * 2, size + OVERLAP * 2) end)
    pcall(function()
        ctl.SetImage(ctl, Enum.ImageSource.StaticReference, RECT_IMG)
        ctl.imageType = Enum.ImageType.Stretch
        if color then
            ctl.imageColor = Color.FromRGBA(color[1], color[2], color[3], 255)
        end
    end)
    CREATED[#CREATED + 1] = ctl
    return ctl
end

-- ---------- 建整幅图（一次画到位）----------
local function buildBoard(pixels)
    local half = (PW - 1) * 0.5
    local t0 = os.clock()
    local failed = 0
    for py = 1, PW do
        for px = 1, PW do
            local col = pixels[(py - 1) * PW + px]
            local ctl = newBlock(col, CELL)
            if ctl then
                ctl:SetAnchoredPosition((px - 1 - half) * CELL,
                                        (half - (py - 1)) * CELL)
                flat[(py - 1) * PW + px] = ctl
            else
                failed = failed + 1
            end
        end
        if py % 32 == 0 then
            log(string.format("  %d/%d 行（%d 控件，%.1f s）",
                I(py), I(PW), I(#CREATED), os.clock() - t0))
        end
    end
    log(string.format("构建完成：%d 控件（失败 %d），%.1f s",
        I(#CREATED), I(failed), os.clock() - t0))
end

-- ---------- 内置渐变数据（无外部数据时用）----------
local function makeGradient()
    local px = {}
    for y = 1, PW do
        for x = 1, PW do
            px[(y - 1) * PW + x] = {
                math.floor(255 * (x - 1) / (PW - 1)),
                math.floor(255 * (y - 1) / (PW - 1)),
                math.floor(255 * (x + y) / (2 * PW)),
            }
        end
    end
    return px
end

-- ---------- 生命周期 ----------
function OnStart()
    log("===== 像素渲染示例 =====")
    host = script.object

    -- ★ 可重入：先清理上一轮
    if #CREATED > 0 then
        for i = 1, #CREATED do pcall(game.DestroyClientUIControl, CREATED[i]) end
        CREATED = {}
        flat = {}
        log("已清理上一轮的 " .. I(#CREATED) .. " 个控件")
    end

    -- ★ 显示鼠标 + 固定角色
    pcall(function() host.showCursor = true end)
    local _, v = pcall(function() return host.showCursor end)
    log("showCursor = " .. tostring(v))
    pcall(function() host.disableKeyEventPassthrough = true end)

    W, H = game.GetUICanvasSize()
    W, H = I(W), I(H)
    log(string.format("画布 %d×%d  CELL=%d  %d×%d 像素  棋盘 %d 单位",
        I(W), I(H), I(CELL), I(PW), I(PW), I(PW * CELL)))

    -- ★ 模板自检
    local ok, probe = pcall(game.InstantiateClientUIControl, TPL_IMG, host)
    if not ok or probe == nil then
        log("首选模板 " .. I(TPL_IMG) .. " 不可用，自动扫描…")
        local t, cls, how = discoverTemplate("ClientUIImageControl")
        if t then
            TPL_IMG = t
            log(string.format("★ 找到模板 %d（%s，来源 %s）", I(t), tostring(cls), how))
        else
            err("!! 找不到可用图片模板 —— 请在编辑器里把图片控件【存为模板】")
            return
        end
    else
        pcall(game.DestroyClientUIControl, probe)
        log("模板确认 " .. I(TPL_IMG))
    end

    -- ★ 取数据（有内联数据就用，否则用内置渐变）
    local pixels
    if PIXEL and PIXEL.RGB and #PIXEL.RGB > 0 then
        pixels = unpackTruecolor(PIXEL.RGB, PW * PW)
        if #pixels ~= PW * PW then
            err(string.format("!! 数据长度 %d != %d，终止", I(#pixels), I(PW * PW)))
            return
        end
        log("已加载内联真彩数据：" .. I(#pixels) .. " 像素")
    else
        pixels = makeGradient()
        log("未提供内联数据，使用内置渐变（" .. I(#pixels) .. " 像素）")
    end

    buildBoard(pixels)

    pcall(function() script:EnableUpdate(true) end)
    log("===== 全部完成，请看屏幕 =====")
end

function OnUpdate(dt) end

function OnDestroy()
    log("[px] OnDestroy")
    if host then
        pcall(function() host:RemoveAllKeyEventListeners() end)
        pcall(function() host:RemoveAllCursorEventListeners() end)
    end
end

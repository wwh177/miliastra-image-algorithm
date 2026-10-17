-- ============================================================
--  01_probe.lua —— 环境探针（★ 每个新项目第一步都跑这个）
--
--  作用：一次性把下列信息打进日志，避免"靠猜"
--    ① 宿主是谁（script.object 的类名）
--    ② 沿父链能否找到 ClientUIContainerControl
--    ③ showCursor / disableKeyEventPassthrough 是否可写、回读值
--    ④ 画布尺寸
--    ⑤ 扫区间找所有"可实例化"的模板，并报告各自的类名
--    ⑥ 枚举存在的按键事件名
--    ⑦ 枚举存在的光标事件名
--    ⑧ 能否取到光标 UI 坐标
--
--  用法：把本文件内容部署为关卡的 external_lua_file\<脚本名>.lua，
--        进入关卡，把日志整段贴给 Agent。
-- ============================================================

local SCAN_RANGES = {
    { 1073741800, 1073742100 },
    { 1073758300, 1073759000 },
}
local KEY_NAMES = {
    "KeyboardCraftspersonKey36Down", "KeyboardCraftspersonKey37Down",
    "KeyboardCraftspersonKey38Down", "KeyboardCraftspersonKey39Down",
    "KeyboardCraftspersonKey40Down", "KeyboardCraftspersonKey41Down",
    "KeyboardMoveForwardKeyDown", "KeyboardMoveBackwardKeyDown",
    "KeyboardMoveLeftKeyDown", "KeyboardMoveRightKeyDown",
    "KeyboardCraftspersonKey18Down", "KeyboardCraftspersonKey19Down",
    "KeyboardCraftspersonKey20Down", "KeyboardCraftspersonKey21Down",
    "KeyboardCraftspersonKey22Down", "KeyboardCraftspersonKey23Down",
    "KeyboardCraftspersonKey24Down", "KeyboardCraftspersonKey25Down",
    "ControllerMenuBackKeyDown",
}
local CURSOR_NAMES = {
    "CursorDown", "CursorUp", "CursorEnter", "CursorExit",
    "CursorDrag", "CursorBeginDrag", "CursorEndDrag", "CursorClick",
}

local function log(...) print("[probe] " .. table.concat({ ... }, " ")) end
local function err(...) printerr("[probe] " .. table.concat({ ... }, " ")) end
local function I(v) return math.floor(tonumber(v) or 0) end

local host = nil

function OnStart()
    log("========================================")
    log("  环境探针")
    log("========================================")

    -- ① 宿主
    host = script.object
    log("script.object = " .. tostring(host))

    -- ② 沿父链找容器
    do
        local node, d, container = host, 0, nil
        while node and d < 12 do
            local cls = tostring(node)
            log(string.format("  父链[%d] = %s", I(d), cls))
            if string.find(cls, "ClientUIContainerControl", 1, true) then
                container = node
            end
            local ok, p = pcall(function() return node.parent end)
            if ok and p and p.alive then node = p else break end
            d = d + 1
        end
        log("容器 = " .. tostring(container))
        if container then
            host = container
            -- ③ 容器开关
            pcall(function() container.showCursor = true end)
            local _, v1 = pcall(function() return container.showCursor end)
            log("showCursor 回读 = " .. tostring(v1))
            pcall(function() container.disableKeyEventPassthrough = true end)
            local _, v2 = pcall(function() return container.disableKeyEventPassthrough end)
            log("disableKeyEventPassthrough 回读 = " .. tostring(v2))
        else
            err("!! 找不到 ClientUIContainerControl")
        end
    end

    -- ④ 画布
    local W, H = game.GetUICanvasSize()
    log(string.format("画布 = %.1f × %.1f 画布单位", W or -1, H or -1))

    -- ⑤ 扫模板
    log("--- 扫描可实例化模板 ---")
    local found = {}
    for r = 1, #SCAN_RANGES do
        local a, b = SCAN_RANGES[r][1], SCAN_RANGES[r][2]
        local n = 0
        for id = a, b do
            local ok, c = pcall(game.InstantiateClientUIControl, id, host)
            if ok and c ~= nil then
                local cls = tostring(c)
                found[#found + 1] = { id = id, cls = cls }
                pcall(game.DestroyClientUIControl, c)
                n = n + 1
            end
        end
        log(string.format("  区间 %d..%d：%d 个", a, b, I(n)))
    end
    log(string.format("模板总数 = %d", I(#found)))
    for i = 1, #found do
        log(string.format("  ★ %d  ->  %s", found[i].id, found[i].cls))
    end
    if #found == 0 then
        err("!! 没有任何可实例化模板 —— 请在编辑器里把图片控件【存为模板】")
    end

    -- ⑥ 按键枚举
    log("--- 存在的按键事件 ---")
    local kn = 0
    for i = 1, #KEY_NAMES do
        if Enum.KeyEventType[KEY_NAMES[i]] ~= nil then
            kn = kn + 1
            log("  ✅ " .. KEY_NAMES[i])
        end
    end
    log("按键可用数 = " .. I(kn))

    -- ⑦ 光标事件枚举
    log("--- 存在的光标事件 ---")
    local cn = 0
    for i = 1, #CURSOR_NAMES do
        if Enum.CursorEventType[CURSOR_NAMES[i]] ~= nil then
            cn = cn + 1
        end
    end
    log("光标事件可用数 = " .. I(cn))

    -- ⑧ 光标坐标
    local ok, x, y = pcall(function()
        local a, b = game.GetCursorUIPos(); return a, b
    end)
    log(string.format("game.GetCursorUIPos() = %s",
        ok and string.format("(%.0f, %.0f)", x or -1, y or -1) or ("失败: " .. tostring(x))))

    -- ⑨ 子控件枚举能力
    local okc, kids = pcall(function() return script.object:GetChildren() end)
    local cnt = 0
    if okc and kids then for _ in pairs(kids) do cnt = cnt + 1 end end
    log("script.object:GetChildren() 数量 = " .. I(cnt))

    log("========================================")
    log("  探针结束，请把以上日志整段粘贴给 Agent")
    log("========================================")
end

function OnUpdate(dt) end
function OnDestroy() log("[probe] OnDestroy") end

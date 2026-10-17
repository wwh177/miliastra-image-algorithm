-- ============================================================
--  02_key_cursor_test.lua —— 按键/鼠标实测探针
--
--  目的：把"键位 ↔ 方向"和"鼠标事件"一次性测清楚
--
--  用法：
--    ① 部署本脚本 → 进关卡
--    ② 依次按 W A S D 和 四个方向键（每个键都会打一行日志）
--    ③ 点击屏幕、拖拽屏幕
--    ④ 把日志整段贴给 Agent —— 由此可确定键位映射与光标是否可用
--
--  屏幕上的现象：
--    · 应该出现鼠标光标（showCursor 已设 true）
--    · 按任意键时日志出现对应键名
-- ============================================================

local KEY_NAMES = {
    "KeyboardCraftspersonKey36Down", "KeyboardCraftspersonKey37Down",
    "KeyboardCraftspersonKey38Down", "KeyboardCraftspersonKey39Down",
    "KeyboardMoveForwardKeyDown", "KeyboardMoveBackwardKeyDown",
    "KeyboardMoveLeftKeyDown", "KeyboardMoveRightKeyDown",
    "KeyboardCraftspersonKey18Down", "KeyboardCraftspersonKey19Down",
    "KeyboardCraftspersonKey20Down", "KeyboardCraftspersonKey21Down",
    "KeyboardCraftspersonKey22Down", "KeyboardCraftspersonKey23Down",
}

local function log(...) print("[test] " .. table.concat({ ... }, " ")) end
local function err(...) printerr("[test] " .. table.concat({ ... }, " ")) end
local function I(v) return math.floor(tonumber(v) or 0) end

local host, W, H = nil, 0, 0
local swipe = nil

function OnStart()
    log("===== 按键 / 鼠标 实测 =====")
    host = script.object
    log("宿主 = " .. tostring(host))

    W, H = game.GetUICanvasSize()
    W, H = I(W), I(H)
    log(string.format("画布 %d×%d", W, H))

    -- 显示鼠标 + 固定角色
    pcall(function() host.showCursor = true end)
    local _, v = pcall(function() return host.showCursor end)
    log("showCursor 回读 = " .. tostring(v))
    pcall(function() host.disableKeyEventPassthrough = true end)

    -- 键盘：每个键都绑，打日志
    local kn = 0
    for i = 1, #KEY_NAMES do
        local name = KEY_NAMES[i]
        local ev = Enum.KeyEventType[name]
        if ev then
            local ok = pcall(function()
                host:AddKeyEventListener(ev, function()
                    log("★ 收到按键: " .. name)
                    return true
                end)
            end)
            if ok then kn = kn + 1 end
        end
    end
    log("已绑定 " .. I(kn) .. " 个按键")

    -- 鼠标：绑到 host + 所有子控件（★ 只绑 host 可能收不到）
    local CE = Enum.CursorEventType
    if CE then
        local targets = { { c = host, tag = "host" } }
        local ok, kids = pcall(function() return host:GetChildren() end)
        if ok and kids then
            local i = 0
            for _, k in pairs(kids) do
                i = i + 1
                targets[#targets + 1] = { c = k, tag = "child" .. i }
            end
        end
        log("光标绑定目标数 = " .. I(#targets))

        local evs = {}
        for _, n in ipairs({ "CursorDown", "CursorUp", "CursorClick",
                             "CursorEnter", "CursorExit" }) do
            if CE[n] then evs[#evs + 1] = { n = n, v = CE[n] } end
        end
        log("将绑定光标事件种类 = " .. I(#evs))

        local bound = 0
        for t = 1, #targets do
            local c, tag = targets[t].c, targets[t].tag
            for e = 1, #evs do
                local nm, ev = evs[e].n, evs[e].v
                local ok2 = pcall(function()
                    c:AddCursorEventListener(ev, function(data)
                        local x, y = 0, 0
                        pcall(function() x, y = data:GetUIPos() end)
                        if nm == "CursorDown" then
                            swipe = { x = x, y = y }
                            log(string.format("★[%s] 按下 (%.0f, %.0f)", tag, x, y))
                        elseif nm == "CursorUp" then
                            if swipe then
                                local dx, dy = x - swipe.x, y - swipe.y
                                swipe = nil
                                log(string.format("★[%s] 抬起 (%.0f, %.0f)  位移(%.0f, %.0f)",
                                    tag, x, y, dx, dy))
                            end
                        elseif nm == "CursorClick" then
                            log(string.format("★[%s] 单击 (%.0f, %.0f)", tag, x, y))
                        else
                            log(string.format("★[%s] %s (%.0f, %.0f)", tag, nm, x, y))
                        end
                    end)
                end)
                if ok2 then bound = bound + 1 end
            end
        end
        log("光标监听已绑定 " .. I(bound) .. " 个")
    else
        err("Enum.CursorEventType 不存在")
    end

    log("========================================")
    log("请依次操作：")
    log("  ① 按 W A S D（每按一次会打一行日志）")
    log("  ② 按 四个方向键")
    log("  ③ 点击屏幕")
    log("  ④ 从屏幕左侧拖到右侧")
    log("  ⑤ 从屏幕上方拖到下方")
    log("然后把日志整段贴给 Agent。")
    log("========================================")
end

function OnUpdate(dt) end
function OnDestroy() log("[test] OnDestroy") end

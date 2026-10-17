-- ============================================================================
--  render.lua —— 最大对齐矩形合并压缩 · 千星奇域渲染器
--               （与 compress.py 的输出配套）
-- ============================================================================
--
--  【用途】
--    把 compress.py 压缩出的块数据在千星奇域关卡里用客户端控件画出来。
--
--  【怎么用】
--    1) 跑 compress.py 得到 output.lua
--    2) 打开本文件，找到下面的 ▼▼▼ 数据区 ▼▼▼，把整段替换成 output.lua 的内容
--    3) 按 README / AGENT_GUIDE 的章节把本文件部署为关卡的 external_lua_file
--
--  【数据格式】（compress.py 生成）
--    IMG.N / IMG.W / IMG.H   边长与逻辑宽高
--    IMG.STD                 使用的容差
--    IMG.ENC                 "b64" 或 "hex"
--    IMG.NBLK                块数（= 需要的控件数）
--    IMG.MAE                 矩形合并的平均色差（仅供参考）
--    IMG.DATA                编码后的块数据
--      hex：每块 10 个 hex 字符 = w,h,r,g,b（各 1 字节）
--      b64：每块 7 个字符 = [3 字节 w,h,r → 4 字符][2 字节 g,b → 3 字符]
--    ★ 坐标 x,y 不存储：块按"行主序扫描顺序"排列，解码端重放扫描即可还原
--
--  【建立方式与性能（实测）】
--    ★ 本渲染器采用「隐藏分组建立 → 建完分帧显示」（见文档 §8.5 / 2D项目-skill）：
--       · 控件挂在【隐藏的全屏透明组】下建立，稳态每帧开销约 1.7 µs/个；
--         若全程可见则是 15~18 µs/个 —— 实测 20,000 个：301 ms/帧(3 fps) → 35 ms/帧，
--         **约 9 倍**。这是"能不能玩"的分水岭。
--       · 建立本身也分帧（默认每帧 40 ms），所以不受"单次回调约 20 s"的看门狗约束；
--         "变可见"这个动作同样分帧（GROUPS 组，每帧一组），避免一帧内重建全部渲染批次。
--    新建控件 ≈ 0.223 ms/个；改属性 ≈ 0.004 ms/次
--    稳态帧开销 = 15~18 µs × 可见控件数（5,000 → 12 fps；20,000 → 3 fps）
--    ★ 隐藏/显示必须用冒号调用：c:SetVisible(false) ✓ ／ c.visible = false ✗（静默失败）
-- ============================================================================


-- ============================================================================
-- ▼▼▼ 数据区：把 compress.py 的输出整段替换到这里 ▼▼▼
-- ============================================================================
local IMG = {}
IMG.N = 4
IMG.W = 4
IMG.H = 4
IMG.STD = 3
IMG.ENC = "hex"
IMG.NBLK = 0
IMG.MAE = 0
IMG.DATA = ""
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
    UNIT = "AUTO",          -- 每个源像素占多少画布单位；"AUTO" = 按画布自适应
    MAX_RATIO = 0.98,       -- 图最多占画布的比例
    MARGIN_PX = 0.20,       -- ★ 每块向外扩多少【源像素】（防拼缝）。必须与分辨率挂钩！
    MARGIN = nil,           -- 兼容旧配置：填了就用它（画布单位，绝对值，高分辨率下会过度外扩）
    GROUPS = 16,            -- ★ 显示分组数：建完每帧显示一组（把"变可见"的成本摊到 K 帧）
    BUDGET = 0.040,         -- ★ 分帧建立每帧预算（秒）；0 = 不分帧（一次建完）
    BUDGET_CHECK = 32,      -- 每这么多个块查一次时钟（os.clock 本身有成本）
    RECT_IMG = 100001,      -- 引擎内置纯色图
    SHOW_CURSOR = true,
    LOCK_CHARACTER = true,
}


-- ============================================================================
-- 实现（通常不需要改动）
-- ============================================================================
local function log(...) print("[render] " .. table.concat({ ... }, " ")) end
local function err(...) printerr("[render] " .. table.concat({ ... }, " ")) end
local function I(v) return math.floor(tonumber(v) or 0) end

local host, template = nil, 0
local canvasW, canvasH = 0, 0
local pool = {}
local groups = {}                                   -- 显示分组（隐藏的透明全屏控件）
local groupHideApiOk = nil                          -- SetVisible/SetActive 是否真的生效（冒号 vs 点号）

-- 建立状态机：0 待命 → 1 隐藏建立中 → 2 分帧显示中 → 3 完成
local PH_IDLE, PH_BUILD, PH_REVEAL, PH_DONE = 0, 1, 2, 3
local phase = PH_IDLE
local decoder, bidx, revealIdx = nil, 1, 1
local made, failed, truncated = 0, 0, false
local layout = nil                                  -- {W,H,unit,side_w,side_h,mg,perGroup,nblk}
local tBuild = 0
local lastLogAt = 0

-- ---- 查表 ----
local HEXV = {}
for i = 0, 9 do HEXV[48 + i] = i end
for i = 0, 5 do HEXV[65 + i] = 10 + i; HEXV[97 + i] = 10 + i end
local B64V = {}
do
    local CH = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    for i = 1, #CH do B64V[string.byte(CH, i)] = i - 1 end
end

-- ---- 扫描推演：由"行主序扫描顺序"还原每块的 x,y ----
-- N = 列数（图宽），H = 图高。H 用于兜底：合法块列表的 y+h 永远 ≤ H，
-- 一旦推演出的行号达到 H，说明数据与图幅不一致，必须停下而不是无限推进。
local function newScan(N, H)
    return { occ = {}, ci = 0, cj = 0, N = N, H = H or N }
end

local function scanNext(S)
    while true do
        if S.cj >= S.H then return nil end        -- ★ 兜底：行号不得越过图高
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

-- ---- 解码器工厂：返回 function(i) -> x,y,w,h,r,g,b（nil 表示结束）----
local function makeDecoder(enc, data, N, H)
    local S = newScan(N, H or N)
    if enc == "b64" then
        return function(i)
            local base = (i - 1) * 7
            local c1, c2, c3, c4, c5, c6, c7 = string.byte(data, base + 1, base + 7)
            if not c7 then return nil end
            local v1, v2, v3, v4 = B64V[c1], B64V[c2], B64V[c3], B64V[c4]
            local v5, v6, v7 = B64V[c5], B64V[c6], B64V[c7]
            if not (v1 and v2 and v3 and v4 and v5 and v6 and v7) then return nil end
            -- 组1：24 位 = w,h,r（每步运算 < 2^24，避免 32 位整数回绕）
            local a = ((v1 * 64 + v2) * 64 + v3) * 64 + v4
            local w = math.floor(a / 65536)
            local h = math.floor(a / 256) % 256
            local r = a % 256
            -- 组2：16 位 = g,b
            local b2 = (v5 * 64 + v6) * 64 + v7
            local g = math.floor(b2 / 256)
            local b = b2 % 256
            local x, y = scanNext(S)
            if not x then return nil end
            scanPlace(S, x, y, w, h)
            return x, y, w, h, r, g, b
        end
    end
    -- 默认 hex：每块 10 字符
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
        if not x then return nil end
        scanPlace(S, x, y, w, h)
        return x, y, w, h, r, g, b
    end
end

-- ---- 模板探测 ----
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
        err(string.format("指定模板 %d 不可用，改为自动探测", RENDER.TEMPLATE))
    end
    for i = 1, #RENDER.TEMPLATE_PRIORITY do
        local t = tryTemplate(RENDER.TEMPLATE_PRIORITY[i])
        if t then log("模板命中优先项 " .. I(t)) return t end
    end
    for id = RENDER.TEMPLATE_SCAN[1], RENDER.TEMPLATE_SCAN[2] do
        local t = tryTemplate(id)
        if t then log(string.format("模板自动探测命中 %d", I(t))) return t end
    end
    return nil
end

local function newRect(parent, x, y, w, h, r, g, b)
    -- ★ 建控件这一套必须 pcall：任一步抛错都会中断整个建立流程，
    --   留下半初始化的场景（OnStart 后面的 showCursor / 屏蔽按键都不会执行）。
    local ok, c = pcall(game.InstantiateClientUIControl, template, parent or host)
    if not ok or c == nil then return nil end
    ok = pcall(function()
        c:SetAnchorMin(0.5, 0.5) c:SetAnchorMax(0.5, 0.5) c:SetPivot(0.5, 0.5)
        c:SetSizeDelta(w, h)
        c.SetImage(c, Enum.ImageSource.StaticReference, RENDER.RECT_IMG)
        c.imageType = Enum.ImageType.Stretch
        c.imageColor = Color.FromRGBA(r, g, b, 255)
        c:SetAnchoredPosition(x, y)
    end)
    if not ok then
        pcall(game.DestroyClientUIControl, c)   -- 不留半成品
        return nil
    end
    return c
end

-- ---- 显示分组（★ 文档 §8.5 的做法：隐藏建立 → 建完分帧显示）----
--  为什么必须这么做：
--   ① 控件挂在【隐藏组】下建立，稳态每帧开销约 1.7 µs/个，而不是可见态的 15~18 µs/个。
--      实测（文档 2D项目-skill）：20,000 个控件 —— 可见 301 ms/帧(3 fps) → 隐藏建立再显示
--      35 ms/帧，**约 9 倍**。这是"能不能玩"的分水岭（文档 §8.5 / 1.3 节）。
--   ② 一次性让全部控件变可见，引擎要在**一帧内**重建整个渲染批次 → 卡顿，甚至被看门狗截断。
--      所以"变可见"这个动作也要分帧：每帧只显示一组。
--  子控件坐标不受影响：组居中、锚点 (0.5,0.5)、位置 (0,0) → 组中心 == host 中心，
--  与"平铺挂在根下"完全等价。
local function newGroup()
    local ok, g = pcall(game.InstantiateClientUIControl, template, host)
    if not ok or g == nil then return nil end
    ok = pcall(function()
        g:SetAnchorMin(0.5, 0.5) g:SetAnchorMax(0.5, 0.5) g:SetPivot(0.5, 0.5)
        g:SetSizeDelta(canvasW, canvasH)
        g:SetAnchoredPosition(0, 0)
        g.SetImage(g, Enum.ImageSource.StaticReference, RENDER.RECT_IMG)
        g.imageType = Enum.ImageType.Stretch
        g.imageColor = Color.FromRGBA(0, 0, 0, 0)       -- 全透明
    end)
    if not ok then pcall(game.DestroyClientUIControl, g); return nil end
    -- ★ 隐藏必须用【冒号调用】。点号赋值（g.visible = false）会静默失败 ——
    --   实测踩过这个坑，还因此误判"隐藏没有收益"。所以这里把 pcall 的返回值记下来。
    local ok1 = pcall(function() g:SetVisible(false) end)
    local ok2 = pcall(function() g:SetActive(false) end)
    if groupHideApiOk == nil then
        groupHideApiOk = (ok1 and ok2)
        log(string.format("分组隐藏 API：SetVisible=%s SetActive=%s（必须都为 true）",
            tostring(ok1), tostring(ok2)))
        if not groupHideApiOk then
            err("⚠️ SetVisible/SetActive 冒号调用失败 —— 隐藏建立无效，"
                .. "稳态帧开销会高约 9 倍。请确认引擎返回的控件对象支持这两个方法。")
        end
    end
    return g
end

local function clearAll()
    for i = 1, #pool do pcall(game.DestroyClientUIControl, pool[i]) end
    pool = {}
    for i = 1, #groups do pcall(game.DestroyClientUIControl, groups[i]) end
    groups = {}
    phase = PH_IDLE
end

-- ---- 打印收尾统计 ----
local function logStats()
    if failed > 0 then
        err(string.format("⚠️ 有 %d 个块建立失败（已丢弃）—— newRect 被 pcall 包住，"
            .. "失败不再是抛错中断，而是静默丢块。请查上一行日志里的错误来源。", I(failed)))
    end
    if truncated then
        err(string.format("⚠️ 数据提前结束：声明 %d 块，实际只解出 %d 块 —— "
            .. "数据区被截断，或块尺寸/图幅与数据不一致（画面会缺一块）",
            I(layout.nblk), I(made)))
    end
    log(string.format("  %dx%d 像素  编码=%s  块数=%d  压缩率=%.2fx  MAE=%.2f",
        I(layout.W), I(layout.H), tostring(IMG.ENC), made,
        (layout.W * layout.H) / math.max(1, made), IMG.MAE or 0))
    log(string.format("  UNIT=%.3f  显示尺寸 %.0f x %.0f 单位（画布 %dx%d）",
        layout.unit, layout.side_w, layout.side_h, I(canvasW), I(canvasH)))
    if #groups > 0 then
        log(string.format("  分 %d 组隐藏建立，建完每帧显示一组（稳态帧开销约降 9 倍）", #groups))
    else
        err("⚠️ 分组创建失败 —— 已回退为「直接挂在 host 下、全程可见」。"
            .. "画面正常，但稳态帧开销会高约 9 倍。")
    end
end

-- ---- 开始一次建立：算布局 + 建隐藏分组 ----
local function startBuild()
    local W = IMG.W or IMG.N
    local H = IMG.H or IMG.N
    local N = math.max(W, H)
    local limit = math.min(canvasW, canvasH) * RENDER.MAX_RATIO
    local unit = RENDER.UNIT
    if type(unit) == "string" then
        unit = limit / N
    else
        local need = N * unit
        if need > limit then
            log(string.format("UNIT %.3f 超出画布，自动改为 %.3f", unit, limit / N))
            unit = limit / N
        end
    end
    local side_w, side_h = W * unit, H * unit
    -- ★ 外扩量必须跟分辨率挂钩。旧版固定 1 画布单位，在 800x800 下相当于每边外扩
    --   约 0.91 源像素；而这类图大多 66% 的块是 1x1，于是每个 1x1 块被画成约 2.8x2.8，
    --   按扫描顺序又互相覆盖 —— 实测把渲染端 MAE 从 1.25 抬到 7.66、60% 像素被改写，
    --   画面出现规律性毛边/锯齿。口径改成"源像素"后与分辨率、画布尺寸都无关。
    local mg = RENDER.MARGIN
    if mg == nil then mg = (RENDER.MARGIN_PX or 0.20) * unit end

    local nblk = I(IMG.NBLK or 0)
    local K = I(RENDER.GROUPS or 16)
    if K < 1 then K = 1 end
    if nblk > 0 and K > nblk then K = nblk end

    clearAll()
    groupHideApiOk = nil
    for _ = 1, K do
        local g = newGroup()
        if g then groups[#groups + 1] = g end
    end

    layout = {
        W = W, H = H, N = N, unit = unit, side_w = side_w, side_h = side_h,
        mg = mg, nblk = nblk,
        perGroup = math.max(1, math.ceil(math.max(1, nblk) / math.max(1, #groups))),
    }
    decoder = makeDecoder(IMG.ENC or "hex", IMG.DATA, W, H)
    bidx, revealIdx = 1, 1
    made, failed, truncated = 0, 0, false
    tBuild = os.clock()
    lastLogAt = 0
    phase = PH_BUILD
    log(string.format("开始隐藏建立：%d 块  %dx%d  ENC=%s  分组 %d 个（每组约 %d 块）"
        .. "  每帧预算 %.0f ms  UNIT=%.3f",
        nblk, I(W), I(H), tostring(IMG.ENC), #groups, layout.perGroup,
        (tonumber(RENDER.BUDGET) or 0.040) * 1000, unit))
end

-- ---- 每帧推进一步：分帧建立 → 分帧显示 ----
local function tick()
    if phase == PH_BUILD then
        local t0 = os.clock()
        local budget = tonumber(RENDER.BUDGET) or 0.040
        local checkEvery = I(RENDER.BUDGET_CHECK or 32)
        if checkEvery < 1 then checkEvery = 1 end
        local ng = #groups
        while bidx <= layout.nblk do
            local x, y, w, h, r, g, b = decoder(bidx)
            if not x then
                if bidx <= layout.nblk then truncated = true end
                bidx = layout.nblk + 1
                break
            end
            local parent = host
            if ng > 0 then
                local gi = math.floor((bidx - 1) / layout.perGroup) + 1
                if gi > ng then gi = ng end
                parent = groups[gi]
            end
            local c = newRect(parent,
                -layout.side_w * 0.5 + (x + w * 0.5) * layout.unit,
                 layout.side_h * 0.5 - (y + h * 0.5) * layout.unit,
                 w * layout.unit + layout.mg * 2,
                 h * layout.unit + layout.mg * 2, r, g, b)
            if c then
                pool[#pool + 1] = c
                made = made + 1
            else
                failed = failed + 1
            end
            bidx = bidx + 1
            if budget > 0 and (bidx % checkEvery == 0) and (os.clock() - t0) >= budget then
                break
            end
        end
        -- 进度日志（约每 1 万块一条，避免刷屏）
        if bidx <= layout.nblk and made >= lastLogAt + 10000 then
            lastLogAt = made
            log(string.format("  建立中… %d / %d 块（%.0f%%），已用 %.1f s",
                I(made), I(layout.nblk), 100.0 * made / math.max(1, layout.nblk),
                os.clock() - tBuild))
        end
        if bidx > layout.nblk then
            log(string.format("隐藏建立完成：%d 个控件（失败 %d），耗时 %.2f s（%s）",
                I(made), I(failed), os.clock() - tBuild,
                truncated and "数据提前结束" or "数据读完"))
            revealIdx = 1
            if #groups > 0 then
                phase = PH_REVEAL
            else
                phase = PH_DONE
                logStats()
                log("===== 就绪 =====")
            end
        end

    elseif phase == PH_REVEAL then
        local g = groups[revealIdx]
        if g then
            -- ★ 必须冒号调用（点号赋值会静默失败）
            pcall(function() g:SetVisible(true) end)
            pcall(function() g:SetActive(true) end)
        end
        revealIdx = revealIdx + 1
        if revealIdx > #groups then
            phase = PH_DONE
            log(string.format("分帧显示完成：%d 组，共 %.2f s", #groups, os.clock() - tBuild))
            logStats()
            log("===== 就绪 =====")
        end
    end
end

function OnStart()
    log("===== 最大对齐矩形合并压缩 · 渲染器 =====")
    host = script.object
    pcall(function()
        local p = host and host.parent
        if p and p.alive then host = p end
    end)
    canvasW, canvasH = game.GetUICanvasSize()
    canvasW, canvasH = I(canvasW), I(canvasH)
    log(string.format("画布 %dx%d  宿主=%s", canvasW, canvasH, tostring(host)))

    if not IMG.DATA or IMG.DATA == "" then
        err("数据区为空：请把 compress.py 的输出粘贴到本文件的『数据区』")
        return
    end

    template = discoverTemplate()
    if not template then
        err("找不到可用的图片控件模板。请按 README『模板准备』章节创建客户端控件模板。")
        return
    end
    log("使用模板 = " .. I(template))
    log(string.format("数据：%dx%d  %d 块  STD=%s  ENC=%s  MAE=%.2f",
        IMG.W or IMG.N, IMG.H or IMG.N, IMG.NBLK or 0, tostring(IMG.STD),
        tostring(IMG.ENC), IMG.MAE or 0))

    if (IMG.NBLK or 0) > 55000 then
        log(string.format("提示：块数 %d 超过单次回调的推荐上限（50,000）——"
            .. "本渲染器已用分帧建立，不受该上限约束；仅需注意稳态帧率"
            .. "（可见控件数 × 15~18 µs/帧）。", IMG.NBLK))
    end

    startBuild()
    tick()                      -- 先推进一步：小图会在这里一次建完，大图则立即开始铺

    local t = script.object
    if RENDER.SHOW_CURSOR then pcall(function() t.showCursor = true end) end
    if RENDER.LOCK_CHARACTER then
        pcall(function() t.disableKeyEventPassthrough = true end)
    end

    pcall(function() script:EnableUpdate(true) end)
    if phase ~= PH_DONE then
        log(string.format("===== 建立中（分帧推进，共 %d 块）=====", I(IMG.NBLK or 0)))
    end
end

-- ★ 分帧推进：隐藏在分组的建立 → 建完后每帧显示一组
function OnUpdate(dt)
    if phase == PH_BUILD or phase == PH_REVEAL then
        tick()
    end
end

function OnDestroy()
    log("[render] OnDestroy")
    -- 先清控件与分组（避免重建时残留）
    for i = 1, #pool do pcall(game.DestroyClientUIControl, pool[i]) end
    pool = {}
    for i = 1, #groups do pcall(game.DestroyClientUIControl, groups[i]) end
    groups = {}
    phase = PH_IDLE
    if host then
        pcall(function() host:RemoveAllKeyEventListeners() end)
        pcall(function() host:RemoveAllCursorEventListeners() end)
    end
end

# 来自 吴玮航 一个晚上与蓝色大肥鱼斗智斗勇的产出

# 千星奇域（原神 UGC / 千星沙箱）2D 小游戏开发实战经验

> 来源：2026-10-07 一次完整实战 —— 在一个已有 3D 关卡里塞进一个可玩的「贪吃蛇」2D 小游戏（选项卡触发、开始按钮、计分计时、退出按钮、可反复重开）。
> 目的：让**另一个 Agent 能在几小时内复现同样的成果，而不是重走 20 多轮弯路**。
> 标注约定：**【实测】** = 亲眼在日志/画面上验证过；**【推断】** = 有证据但未直接验证；**【未解】** = 至今没搞明白。

---

## 0. TL;DR —— 如果只读 10 行

1. **`.gil` 不能改**。编辑器在「进入关卡」时会用自己的副本把 `.gil` 整份重写，你写进去的任何东西（脚本、控件组、界面）都会被丢弃。
2. **权威的脚本源码是 `external_lua_file\<名字>.lua`**，改它 + 退出关卡再进关卡就生效，**连编辑器都不用重启**。这是唯一的快速迭代通道。
3. **关卡结构（界面控件布局、控件、节点图）只能在编辑器 UI 里手工做**，Agent 只能读 `.gil` 分析、给操作指引。
4. **不要用 `game.InstantiateClientUIControl`**。实测 6 个父节点 × 43 个索引 = 258 次组合全部返回 `nil`。用「**控件池**」方案：让用户在画布上摆好一批控件，脚本用 `game.GetClientUIControl(id)` 拿回来复用。
5. **`game.GetClientUIControl(id)` 是最重要的诊断手段** —— 它能按运行时 ID 把活着的客户端控件连同类名、名字、`prefabIndex`、`parent`、子控件数全列出来。
6. **`SetSiblingIndex(k)` 是「插入」不是「赋值」**，会把 `>= k` 的控件整体挤后一格。定层级必须用**递增游标**一次排完。
7. **节点图引脚有类型**：「实体」≠「玩家」，接错会报「节点参数设置错误」。876 个节点里**只有 `[259]` 能把「角色实体」转成「玩家实体」**。
8. **「预设按钮」控件没有外观也没有 `text` 字段**，只有 `interactable` / `clickAudioId` / `raycastTarget`。按钮要自己用「图片 + 文本框」画。
9. **每个 API 调用都套 `pcall`**。字段名写错时赋值会静默失败，不套 pcall 会在别处炸。
10. **Lua 局部变量只在声明之后可见**。跨段互相调用必须写前置声明（`local foo` + 后面 `foo = function() ... end`），否则调用点拿到的是全局 `nil`。
11. **客户端控件会被引擎销毁重建**（传送 / 容器显隐切换时），`OnStart` 会在一次游玩里跑很多次 —— 脚本必须可重入，
    而且**容器打开/关闭必须成对**，否则小游戏会在传送时自己蹦出来。**详见 §15（最难的坑）**。

---

## 1. 环境与文件布局

### 1.1 编辑器

- 桌面辅助编辑器 **BeyondEditor.exe**（「千星沙箱」）：`F:\Genshin Impact Game\BeyondAssets\BeyondAssistEditor\`
- 实测版本：CN `7.1.0.48145775`
- 运行时会拉起两个进程：主窗口 + 「日志」窗口
- **有内核级反作弊**（`C:\Windows\system32\HoYoKProtect.sys`）：
  - 窗口类名被混淆成单字母
  - UI Automation 树只暴露根节点（ControlView / RawView 都不行）
  - **结论：编辑器无法被自动化。不要尝试注入/模拟输入**，既有账号风险也没必要
  - 屏幕**只读**（截图）不受影响

### 1.2 关卡文件位置

```
%USERPROFILE%\AppData\LocalLow\miHoYo\原神\BeyondLocal\<UID>\
  Beyond_Local_Save_Level\<关卡ID>\
      <关卡ID>.gil                          ← 编辑器生成的整份副本（别改）
      external_lua_file\<脚本名>.lua         ← ★ 权威脚本源码（改这个）
  Temp\<关卡ID>.gil                          ← 工作副本（别改）
  Beyond_Debug_Log\*.gia                     ← 运行日志（不一定生成）
```

UID 例：`342243974`；关卡 ID 例：`1073741835`（关卡名「FZU千星社群纳新_1」）。

### 1.3 文件格式

- `.gil` = 关卡存档，`.gia` = 项目资产
- **没有加密**：`[20 字节文件头] + [明文 protobuf] + [4 字节尾部]`
- 文件头 = 5 个大端 uint32：`head[0] = 总长-4`、`head[4] = 总长-24`（改内容必须重算）
- 解析对齐**必须用可验证签名**（`u32@0 == total-4` 且 `u32@(N-4) == total-4-N`），**不要用启发式猜偏移** —— 曾经因为猜成 18 而不是 20，把玩家的关卡文件写坏过一次

关键字段路径（实测）：

| 路径 | 含义 |
|---|---|
| `#1` / `#2` | 关卡 ID / 关卡名 |
| `#9.501` | **根控件组 ID 列表**（packed varint） |
| `#9.502[i]` | 第 i 个「界面控件组」 |
| `#9.502[i].501` | 控件组 ID |
| `#9.502[i].504` | 父级/继承模板 ID（**没有 504 = 根控件组**） |
| `#9.502[i].505` | 根控件（`.505.12.501` = 控件名） |
| `#9.502[i].505[j]` | 第 j 个子控件（`.503.504.4` = 所属控件组 ID） |
| `#9.502[容器].505[3].503.73.501` | **客户端控件容器的「画布根控件组 ID」** |
| `#50.1.1` / `.2` / `.3` / `.5` | 脚本映射 ID / 脚本名 / **文件名** / Lua 源码 |

---

## 2. 铁律：`.gil` 是只读的（血泪教训）

### 2.1 现象

- 离线把补丁写进 `.gil`（脚本、控件组都试过）
- 用户重新打开编辑器、进入关卡后：
  - **内嵌 Lua 源码被改回旧版**（实测：补丁后 93033 字节 → 进关卡后回滚成旧源码 26279 字节）
  - **之前搬进去的 3 个控件组凭空消失**（`.gil` 从 89951 字节变回 87763 字节）

### 2.2 结论

编辑器持有自己的一份权威数据，**在「进入关卡」时整份重写 `.gil`**。
→ **`.gil` 里除了 `external_lua_file` 之外的东西，一律保不住。**

### 2.3 唯一有效的迭代通道

```powershell
# 改脚本 = 只覆盖这个文件，然后用「退出关卡 → 重新进入关卡」生效（无需重启编辑器）
Copy-Item 新脚本.lua "…\Beyond_Local_Save_Level\<关卡ID>\external_lua_file\<脚本名>.lua" -Force
```

要点：
- **文件名必须与 `#50.1.3` 一致**，否则编辑器显示「引用丢失 xxx.lua」
- 实测：**不用重启编辑器**，退出关卡再进就生效（这一点极大加速了迭代）
- 不要指望改 `.gil` 里的 `#50.1.5` 有用

### 2.4 用户配合的节奏

一次有效迭代 ≈ 20 秒：**改文件 → 退关卡 → 进关卡 → 看日志/截图**。
所以脚本里要**一次性把诊断信息打全**，避免「改一次日志、再跑一次」的循环。这条经验值至少 5 轮往返。

---

## 3. 客户端脚本系统

### 3.1 运行环境

- **Lua 5.3**；但 `string.dump`、`io.*` 不可用
- 脚本挂载在「客户端控件」上，随控件存在而存在
- 日志用 `print(...)` / `printerr(...)`，出现在编辑器的「日志」窗口

### 3.2 生命周期回调（实测行为）

| 回调 | 实测触发时机 |
|---|---|
| `OnInit` | 脚本实例创建 |
| `OnEnable` | 控件「被启用」—— 实测**只在关卡开始时触发一次**，**不是**容器显示/隐藏时 |
| `OnStart` | 紧接着 OnEnable |
| `OnUpdate(dt)` | 需要 `script:EnableUpdate(true)` |
| `OnDisable` / `OnDestroy` | 控件被停用/销毁 |

> **重要实测**：容器「初始可见性 = 关」**并不阻止脚本运行** —— 进关卡时 `OnEnable` + `OnStart` 照样跑。
> **推论**：脚本不能靠 `OnEnable` 感知容器被显示/隐藏，**「重开一局」必须由服务端主动通知客户端**（见 §8）。

### 3.3 双实例问题（本关特有，但很典型）

本关的「客户端控件容器」画布里有**两个「容器节点」**（一个套在另一个里），两个都挂了同一个脚本 → **`OnStart` 跑两遍，日志翻倍，界面会建两套**。

两种去重手段（脚本里都实现了）：
```lua
-- 1) 只认指定宿主的模板索引
if HOST_PREFAB > 0 and parent.prefabIndex ~= HOST_PREFAB then return end
-- 2) 容器嵌套检查：嵌在另一个客户端控件容器里的那个跳过
if isNestedContainer(container) then return end
```
实测宿主 `prefabIndex` 分别是 `1073741853`（外层）和 `1073741855`（嵌套），日志里 `script.object` 是 `ClientUIContainerControl:1` / `:30`。

---

## 4. 客户端控件体系（必须搞清楚的三个概念）

| 概念 | 是什么 | 在哪 |
|---|---|---|
| **界面控件组库** | 一堆「界面控件组」的仓库（一个组 = 一棵控件树） | `#9.502`，编辑器「界面控件组管理 → 界面控件组库」 |
| **客户端控件模板** | 「存为模板」的客户端控件（编辑器里那个 tab 默认是**空的**） | 同上，「客户端控件模板」子页 |
| **客户端控件容器** | **服务器控件**，作用是把客户端控件显示到主屏上 | 界面布局里；本关 ID `1073741852` |
| **容器画布** | 客户端控件真正被摆放的地方 | 容器 →「画布设置 → 前往编辑」 |

**官方规则（原文）**：
> 「运行时，**仅当客户端控件所处的客户端控件容器状态处于「激活且可见」时**，客户端控件和脚本才正常生效」
> 「除**客户端控件容器画布中的客户端控件**以及**客户端控件模板中的控件**外，其他控件均为服务器控件，**服务器控件的模板索引无法被客户端脚本调用**」
> 「**仅存为模板**的客户端控件的父节点，支持通过接口 `ClientUIBaseControl` 被动态创建」

### 4.1 本关的实际结构（`.gil` 解出来的）

```
[23] 1073741844  -            ClientUIPrototypeHierarchyRoot    ← 模板层级根
[24..27]  1073741851/54/50/49   预设按钮 / 光标检测区域 / 文本框 / 图片
[28] 1073741853  -            容器节点                          ← 画布根（= 容器引用的那个）
[29..33]  1073741862/61/60/59/55  预设按钮 / 光标检测区域 / 图片 / 文本框 / 容器节点  ← 画布里的控件
[15] 1073741852  1073741825   客户端控件容器
     └─ 9.502[15].505[3].503.73.501 = 1073741853   ← 容器 → 画布根的引用
```

加上用户后来手工加的：**19 张图片 + 4 个文本框 + 4 个预设按钮 + 1 个光标检测区域 + 1 个容器节点 = 29 个子控件**。

---

## 5. `InstantiateClientUIControl` 的坑（最重要的一条）

### 5.1 症状

`game.InstantiateClientUIControl(prefabIndex, parent)` **永远返回 `nil`**。

### 5.2 做过什么

- 6 个候选父节点（`script.object`、运行时 id 1~6 的每个控件、`nil`）× 43 个候选索引
- **258 次组合，全部 `nil`**
- 候选里包含**运行时扫描确认存在、`prefabIndex` 就是它自己的那些控件**（例如 `1073741860` 图片、`1073741859` 文本框、`1073741861` 光标区域、`1073741862` 预设按钮）

### 5.3 已知的语义

- **控件的运行时 `prefabIndex` == 它所属控件组的 ID**（实测：画布里的图片控件报 `prefabIndex = 1073741860`，而 `#9.502` 里 `1073741860` 就是「图片」那个组）
- **画布控件 = 普通界面控件组，不是「已存为模板」的控件**
- 结合官方那句「**仅存为模板**的客户端控件的父节点，支持被动态创建」→
  **【推断】只有「存为模板」过的控件才能被实例化；画布里的控件不行。**
  （这条没最终验证：用户当时不想再做「存为模板」实验，我们直接绕开了）

### 5.4 结论 / 建议

**不要在这上面继续投入。** 直接走「控件池」方案，它不依赖任何未知索引，而且已经跑通了完整的游戏。

> 唯一没试过的分支：「在画布编辑里选中控件 → 点底部【存为模板】」。
> 如果要验证，方法：改动前后各存一份 `.gil`，用 `--ui` 对比，新出现的控件组 ID 就是模板索引；再用探针脚本试实例化。

---

## 6. 控件池方案（推荐做法）

### 6.1 思路

让用户**在容器画布上摆好一批控件**（图片 × N、文本框 × 3、光标检测区域 × 1），脚本开局把它们的运行时 ID 全部扫出来，**按角色分配 + 只切显隐**，不创建、不销毁。

### 6.2 扫描（最关键的一段代码）

```lua
local poolImages, poolTexts, poolButtons, poolAreas = {}, {}, {}, {}
for id = 1, 80 do
    local ok, c = pcall(game.GetClientUIControl, id)
    if ok and c then
        local cls = tostring(c)                    -- 例 "ClientUIImageControl:4"
        if     string.find(cls, "CursorEventArea", 1, true) then poolAreas[#poolAreas+1] = c
        elseif string.find(cls, "Image",           1, true) then poolImages[#poolImages+1] = c
        elseif string.find(cls, "TextBox",         1, true) then poolTexts[#poolTexts+1] = c
        elseif string.find(cls, "Button",          1, true) then poolButtons[#poolButtons+1] = c
        end
    end
end
```

判类名时的**顺序很重要**：先判 `CursorEventArea`，再判 `Image`（否则会误判）。

实测扫出来的清单（对你的调试极有价值）：
```
id=1  ClientUIContainerControl:1        name=容器节点    prefab=1073741853
id=2  ClientUIPresetButtonControl:2     name=预设按钮    prefab=1073741862
id=3  ClientUICursorEventAreaControl:3  name=光标检测区域  prefab=1073741861
id=4  ClientUIImageControl:4            name=图片       prefab=1073741860
id=5  ClientUITextBoxControl:5          name=文本框      prefab=1073741859
id=6  ClientUIContainerControl:6        name=容器节点    prefab=1073741855
```

**运行时 ID 的规律**【实测】：`id = 1` 是画布根，其余按 `#9.502` 列表顺序递增，而该列表顺序 = 编辑器画布树的顺序。

### 6.3 角色分配（固定，不动态取用）

```lua
MAXSEG    = #poolImages - 4        -- 留 底板/棋盘/豆子/按钮底图
bgCtrl    = poolImages[1]          -- 全屏不透明底板（盖住 3D）
boardCtrl = poolImages[2]          -- 棋盘
foodCtrl  = poolImages[3]          -- 豆子
btnBg     = poolImages[#poolImages]-- 按钮底图
segSlots  = { poolImages[4] … poolImages[#poolImages-1] }   -- 蛇身槽（空闲栈管理）

hudCtrl   = poolTexts[1]           -- HUD
hintCtrl  = poolTexts[2]           -- 底部提示
btnLabel  = poolTexts[3]           -- 按钮文字
```

**为什么固定角色**：动态 `acquire/release` 会让控件层级乱飘（见 §6.5），固定下来后每个控件的层级一次定死。

### 6.4 开局先全部隐藏

```lua
-- 画布上新加的控件默认是「可见 + 摆在画布正中」，不先藏起来屏幕上会堆一片方块
for _, list in ipairs({poolImages, poolTexts, poolButtons, poolAreas}) do
    for i = 1, #list do pcall(function() list[i]:SetVisible(false) end) end
end
```

### 6.5 层级（`SetSiblingIndex` 的插入语义）★ 踩坑最惨的一处

**官方 API 文档**：`SetSiblingIndex(index)`「数值越大通常越靠后、**显示越靠上**」—— 这条**实测正确**。

**但是**：它是「插入」语义 —— 把某控件设到索引 `k`，会把原本 `>= k` 的控件**整体挤后一格**。

错误做法（我第一版）：给每个角色预先算好固定索引，然后逐个 `SetSiblingIndex`：
```
设 区域→2   （底板3→4、棋盘4→5）
设 蛇身1→5  （棋盘 5→6）      ← 棋盘被挤到蛇身上面了
最终：底板(4) < 蛇身(5,6,7) < 豆子(8) < 棋盘(9)   ← 棋盘盖住一切（不透明的！）
```
症状：**HUD 可见、蛇几乎看不见**（HUD 被挤到最高层）。

正确做法（最终版）：**从下到上，用递增游标依次插入**
```lua
local layerCursor = 0
local function placeLayer(ctrl, tag)
    if not ctrl then return end
    local idx = layerCursor
    layerCursor = layerCursor + 1
    pcall(function() ctrl:SetSiblingIndex(idx) end)
    -- 可选：读回 GetSiblingIndex() 打日志验证
end

resetLayer()
placeLayer(swipeArea, "区域")     -- 0  最底：只负责接光标
placeLayer(bgCtrl,    "底板")     -- 1
placeLayer(boardCtrl, "棋盘")     -- 2
placeLayer(foodCtrl,  "豆子")     -- 3
for i = 1, MAXSEG do placeLayer(segSlots[i], nil) end   -- 4..18
placeLayer(hudCtrl,   "HUD")      -- 19
placeLayer(hintCtrl,  "提示")     -- 20
placeLayer(btnBg,     "按钮底")    -- 21
placeLayer(btnLabel,  "按钮字")    -- 22 最上
```

要点：
- **必须一次排完**，之后运行期再也不碰 `SetSiblingIndex`
- 排完之后再配置外观（`SetSizeDelta` / `SetImage` / 颜色 / 文本）
- 日志里同时打印「请求索引」和 `GetSiblingIndex()` 的**回读值**，一眼能看出引擎有没有裁剪

### 6.6 绘制顺序相关的其它实践

- **图片 / 文本一律 `raycastTarget = false`**，这样点击能穿过它们到达全屏光标区域
- **全屏光标区域不要 `SetAsLastSibling()`** —— 它会盖住按钮抢掉点击。正确做法是把它放在**最底层**，只靠 `raycastTarget = true` 接事件
- 按钮底图 / 按钮文字的层级放在 HUD 之上，保证不被蛇身压住
- 按钮和底部提示位置重叠 → 显示按钮时把提示 `SetVisible(false)`，按钮消失再放回来

### 6.7 控件不足时的降级

```lua
if #poolImages < 8 or #poolTexts < 3 then
    -- 用 poolTexts[1] 在屏幕正中打一段黄字，直接告诉用户缺几个、去哪儿加
    -- 然后 script:EnableUpdate(false) 退出，别让 OnUpdate 空转刷错误
end
```
**别让失败静默** —— 这一条省了很多次「屏幕上什么都没有，不知道为什么」的沟通。

### 6.8 需要的控件数量（给用户的开单）

| 控件 | 数量 | 用途 |
|---|---|---|
| 图片 | ≥8，建议 16~19 | 1 底板 + 1 棋盘 + 1 豆子 + 1 按钮底图 + 剩下全是蛇身槽 |
| 文本框 | ≥3 | HUD / 底部提示 / 按钮文字 |
| 光标检测区域 | 1 | 滑动 + 点击命中（全屏） |
| 预设按钮 | 0 | **用不上**（见 §7.3） |

用户加控件的位置（**要一字不差地这么指路**）：
```
界面控件组管理 → 界面布局 → 布局详情/自定义 → 点「客户端控件容器」
  → 右侧「画布设置」→【前往编辑】
  → 左下角【添加控件】→ 选「图片」/「文本框」
  → 更快的办法：选中已有控件 Ctrl+C / Ctrl+V
```

---

## 7. 输入与交互

### 7.1 键盘

```lua
parent:AddKeyEventListener(Enum.KeyEventType.KeyboardCraftspersonKey36Down, fn)  -- ↑
-- 36/37/38/39 = ↑ ↓ ← →；KeyboardMoveForward/Backward/Left/RightKeyDown = WASD
-- KeyboardCraftspersonKey18Down = P
```
- **没有 Esc**（`Enum.KeyEventType` 里没有）；手柄的返回键是 `ControllerMenuBackKeyDown`
- 回调返回 `true` 表示吞掉该事件

### 7.2 光标：坐标换算（做按钮命中必看）

`Enum.CursorEventType` 有 `CursorDown / CursorUp / CursorEnter / CursorExit / CursorDrag / CursorBeginDrag / CursorEndDrag / CursorClick`。

回调收到的是 `CursorEventData`：
- `data:GetUIPos()` → `x, y`，**以画布左下角为原点**
- 控件用的是 `SetAnchoredPosition(x, y)`，**以父控件中心为原点**

换算与命中判定：
```lua
local x, y = data:GetUIPos()
local cx, cy = x - W * 0.5, y - H * 0.5          -- W,H = game.GetUICanvasSize()
if math.abs(cx - r.x) <= r.w * 0.5 and math.abs(cy - r.y) <= r.h * 0.5 then act() end
```
实测日志：`点击 UI坐标(847,60) → 中心坐标(47,-390)` 正好命中 `位置(0,-385) 尺寸304x76` 的按钮。

**踩坑**：只把 `CursorClick` 绑在全屏光标区域上是不够的 —— 动作函数里一旦抛错就会静默中断。**用 `pcall` 包住动作**：
```lua
local ok, err = pcall(act)
if not ok then printerr("[snake] 按钮动作出错: " .. tostring(err)) end
```
这一条让一个隐藏了两轮的 bug 立刻现形。

### 7.3 「预设按钮」控件是个陷阱

官方文档《预设按钮控件》原文：
> 预设按钮**本身没有外观**，「可以**引用子层级中的客户端控件**，作为不同状态节点的外显样式」

API 里 `ClientUIPresetButtonControl` 只有三个字段：
```
interactable    是否可交互
clickAudioId    点击音效 ID
raycastTarget   可被光标射线检测
```
**没有 `text` 字段，没有外观。**

→ 只设 `btn.text = "开始游戏"` 会**静默无效**，按钮是个看不见的东西，点上去也没反应。
**→ 正确做法：用「图片（圆角色块）+ 文本框（文字）」自己画按钮，点击由全屏光标区域 + 坐标命中判定。**

### 7.4 `showCursor`（常驻光标）★ 已解决（答案在 §15）

- 字段在 `ClientUIContainerControl` 上：`showCursor`（读写），「CursorEvent 相关方法都需设置该参数为真后才可正常使用」
- 开局设 `true` → 光标出现，点击事件正常
- **曾经的现象**：退出时设回 `false`，光标不消失。已排除字段名/类型/权限问题（都核对过官方文档），
  全量清扫（遍历所有客户端控件把 `showCursor` 置 false，日志确认「清理 2 个」）也没用。
- **真正的原因**：不是 `showCursor` 这一层。**只要「客户端控件容器」没有被服务端关掉，
  客户端控件就一直活着，常驻光标就一直挂着**。
- **真正的修法**：退出时让服务端 `[384] 设置界面控件(组)状态 → 显示状态=关闭` 把**容器本身**关掉
  （接线见 §8.3 / §15）。容器一关，控件被销毁，光标自然消失 —— 实测确认。
- 客户端那套 `clearHostFlags()`（遍历所有控件清 `showCursor` / `disableKeyEventPassthrough`）**可以保留**，
  它是无害的兜底；但**不要指望它单独解决问题**。

### 7.5 `disableKeyEventPassthrough`（屏蔽按键穿透）

- 也在 `ClientUIContainerControl` 上
- 打开后 **WASD 不会再让 3D 角色乱跑**
- **时机很重要**：不要在关卡开始就打开（否则玩家还没点选项卡，角色就先动不了了）。放在「点开始游戏时」打开，「点退出时」恢复

### 7.6 一个隐藏很深的顺序 bug（务必引以为戒）

```lua
-- ❌ 错误：开关设置在「宿主去重检查」之前
if container then setShowCursor(true) end
if HOST_PREFAB > 0 and parent.prefabIndex ~= HOST_PREFAB then return end
```
后果：**两个脚本实例都设了自己容器的 `showCursor = true`**；退出时只清得掉一个（从 `script.object` 沿父链往上走，够不到嵌套的那个）→ 光标残留。

**教训：所有「全局副作用」（改容器开关、注册监听、改其它控件）都必须放在去重检查之后。**

---

## 8. 服务端节点图

### 8.1 用到的节点（从本地节点目录挖出来的，共 876 个）

| 节点 | 入参 | 出参 |
|---|---|---|
| `[307] 选项卡选中时` | — | 事件源实体 / 事件源GUID / **选项卡序号** / **选择者实体** / GUID |
| `[316] 界面控件组触发时` | — | 事件源实体 / 事件源GUID / 界面控件组组合索引 / **界面控件组索引** |
| `[306] 激活/关闭选项卡` | 目标实体 / 选项卡序号 / 是否激活 | — |
| `[383] 激活控件组库内界面控件组` | **目标玩家** / 界面控件组索引 | — |
| `[384] 设置界面控件(组)状态` | **目标玩家** / 界面控件(组)索引 / 显示状态 | — |
| `[521] 移除控件组库内界面控件组` | **目标玩家** / 界面控件组索引 | — |
| `[300001] 监听信号` | — | **事件源实体 / 事件源GUID / 信号来源实体**（全是「实体」类型） |
| `[300005] 发送客户端脚本信号` | 目标玩家 + 输入框「**信号名**」 | — |
| `[248] 获取在场玩家实体列表` | — | **玩家实体列表** |
| `[128] 获取列表对应值` | 列表 / 序号 | 值 |
| `[259] 获取角色归属的玩家实体` | **角色实体** | 所属玩家实体 |
| `[382] 切换当前界面布局` | 目标玩家 / 布局索引 | — |
| `[1] 打印字符串` | 字符串 | — |

### 8.2 引脚类型系统 ★ 一个大坑

**「实体」和「玩家」是两个不同的引脚类型，不能互接**，否则试玩时报：
```
⚠ 试玩校验失败，请解决其他设置错误
⚠ 服务器节点图设置错误, ID: 1073741831
⚠ 节点参数设置错误, 节点ID: 2, 上一个连线节点ID: 1
```

**`[300001] 监听信号` 的三个输出全是「实体」类型**，所以**不能**接到 `[384]` 的「目标玩家」上。
我把 876 个节点全过滤了一遍：**能把「实体」转成「玩家实体」的只有 `[259]`，而它要求输入必须是「角色实体」** —— 客户端信号给的实体不保证是角色。

**可用的替代路径**：`[248] 获取在场玩家实体列表` → `[128] 获取列表对应值(序号)` → 「目标玩家」。
（单人试玩完全正确；多人的话只会作用于列表里第一个玩家。）

### 8.3 最终架构（推荐）

**核心决策：显示/隐藏交给服务端（因为需要「玩家」）；退出动作交给客户端（因为它自己就能隐藏自己的控件）；重开靠服务端发一个客户端脚本信号。**

> ⚠️ **A 和 B 必须成对存在！只做 A 不做 B 会引来一个非常难查的诡异 bug**（点带传送功能的选项卡会自己蹦出小游戏）—— 机制与完整复盘见 **§15**。

```
【A. 按选项卡进入】★ 一定要加条件筛选，否则任何选项卡都会触发
[307] 选项卡选中时
   ├─ 选项卡序号 ──▶ [是否相等] 输入2 = 1 ──▶ [双分支] 条件
   │                                          （或用 事件源GUID，见下方"重要经验"）
   ├─ 双分支·是 ──┬──▶ [384] 设置界面控件(组)状态
   │              │        目标玩家         = ← 选择者实体
   │              │        界面控件(组)索引  = 1073741852（客户端控件容器）
   │              │        显示状态         = 显示
   │              │
   │              └──▶ [300005] 发送客户端脚本信号
   │                       目标玩家 = ← 选择者实体
   │                       信号名   = SnakeReset        ← 脚本里 script:RegisterServerSignalHandler("SnakeReset", …)
   └─ 选择者实体 ──▶ 上面两个节点的「目标玩家」

【B. 点游戏内退出按钮 → 收起界面】★ 缺了这块 = §15 那个 bug
[300001] 监听信号     信号名 = SnakeExit
   └─ 执行输出 ──▶ [384] 设置界面控件(组)状态
                     目标玩家         = ← [128] 的「值」
                     界面控件(组)索引  = 1073741852
                     显示状态         = 关闭          ← 必须真的关掉容器

[248] 获取在场玩家实体列表 ──「玩家实体列表」──▶ [128] 获取列表对应值（序号 0，不行试 1）
```

配套的客户端代码：
```lua
-- 注册（只注册一次）
script:RegisterServerSignalHandler("SnakeReset", function(signalName, params)
    print("[snake] 收到服务器信号 " .. tostring(signalName) .. " → 重新初始化一局")
    setupGame()
end)

-- 退出时发服务端信号（带参数，方便做结算）
local sig = game.ServerSignal("SnakeExit")
sig:AddInt(score)
sig:AddInt(math.floor(elapsed))
sig:SendSignal()
```

**重要经验**：
- 选项卡**必须**用 `[307] 选项卡选中时`（它的「选择者实体」是**合法的玩家引脚**）；如果它其实是「界面控件组」，用 `[316]`
- **`[383] 激活控件组库内界面控件组` 用不上** —— 你的容器已经在「界面布局」里了，应该用 `[384] 设置界面控件(组)状态`
- **筛选条件优先用「选项卡序号」**：`[307]` 有两个 GUID 输出（`事件源GUID` / `GUID`），从命名看 `事件源GUID` 很可能是**事件源实体（玩家/角色）的 GUID**，而不是选项卡自己的编号；`选项卡序号` 语义唯一、不会有歧义
- 信号名两端必须**一字不差**
- **`SnakeReset` 会在「控件刚被重建」的那一瞬间漏收**（新实例还没注册监听，信号已经发走了）。
  所以它只能当"锦上添花"，**不能**作为「界面出现」的可靠手段 —— 界面出现靠 `OnStart`（见 §15）
- 节点图**挂在 `实体节点图 → 总体`**（关卡级），不要挂在某个机关/造物上 —— 选项卡是关卡级 UI 事件

### 8.4 一次踩过的错：节点图挂在「石质机关 - 17」上

日志窗口左侧能看到每个节点图的宿主（`贪吃蛇 生效 / 石质机关 - 17`），还带 ⚠ 警告图标。
**排查时先看这个** —— 宿主不对，事件根本收不到。

---

## 9. Lua 静态检查清单（这个项目踩了两次的坑）

### 9.1 局部变量「先用后声明」★

Lua 的局部变量**只在声明之后可见**。在声明之前调用，拿到的是**全局变量（nil）**：

```lua
-- ❌ 运行时报 "attempt to call a nil value (global 'hideActionButton')"
--    而且是在函数中途炸掉，后面的代码全部不执行 → 表现成「点了没反应」
local function onExitClicked()   -- 行 421
    hideActionButton()           -- ← 这里看到的是全局 nil
end
local function hideActionButton()  -- 行 633 才声明
    ...
end
```

**正确写法**：
```lua
local hideActionButton                       -- 前置声明（也不能漏！）
local function onExitClicked() hideActionButton() end
hideActionButton = function() ... end        -- ← 注意是赋值，不是再写一次 local！
```

**两个陷阱叠加**：
1. 漏前置声明 → 调用点拿到全局 nil
2. 加了前置声明但后面写成 `local function hideActionButton()` → **新的 local 遮蔽了前置声明**，前面的引用仍然是 nil

同类问题还有一次：`PREFAB_AREA` 用了但从没声明（静默 nil）。
**→ 已固化成 `luacheck.js` 的自动检查项**（见 §10.3）。

### 9.2 `table.remove` + 先置 nil

```lua
-- ❌ 把槽位置 nil 之后，调用方紧接着 table.remove(t)，#t 已经缩短 → 会多删一个元素
--    → 逻辑表与显示表长度不一致 → 「蛇跑几步就画乱」
local function destroySeg(i)
    local c = segCtrls[i]
    if c then kill(c) end
    segCtrls[i] = nil          -- ❌ 别这么写
end
```
→ **释放资源就好，不要动槽位**；数组的删除交给调用方的 `table.remove` 统一做。

### 9.3 释放函数要幂等

```lua
local function releaseSegSlot(ctrl)
    for i = 1, #segFreeStack do
        if segFreeStack[i] == ctrl then return end   -- 已经在空闲栈里就别再压一次
    end
    segFreeStack[#segFreeStack + 1] = ctrl
    pcall(function() ctrl:SetVisible(false) end)
end
```
否则「重新初始化」时同一个控件会被同时分给两节蛇身。

### 9.4 一切存疑调用都套 `pcall`

字段名写错 → 赋值静默失败；方法不存在 → 报错中断。
**项目里几乎每个 API 调用都套了 `pcall`**，尤其是这些「可能有也可能没有」的字段：
`showCursor` / `disableKeyEventPassthrough` / `adaptiveFontSize` / `horizontalAlignment` / `bgColor` / `raycastTarget` / `SetAsLastSibling`

### 9.5 初始化必须可重入

因为「重开一局」会再跑一遍 `setupGame()`：
- 空闲栈要重置
- 监听注册要有一次性开关（`resetHandlerRegistered`）
- `bindKeys` 要有 `if next(keyHandlers) ~= nil then return end` 的守卫
- **`bindSwipe` 不能直接 return** —— 退出时整块光标区域被隐藏了，重开必须**重新 `SetActive/SetVisible/SetSizeDelta/SetAnchoredPosition`**，只跳过监听注册。
  （这一条正是「退出后无法再次进入游戏」的原因：区域一直是隐藏的 → 按钮点不动）

---

## 10. 工具链

全部在 `E:\DSHworker\` 下（shell 脚本/工具目录另建亦可）：

### 10.1 `.gil` 分析

| 工具 | 用途 |
|---|---|
| `tools\ugc-json.js` | `.gil/.gia ⇔ JSON` **无损**互转（已验 SHA256 一致）；`to-bin` 会重算文件头长度并做**强制结构自检**，不一致就拒绝写出 |
| `tools\probe-gil.js` | `<file> --ui` 列控件组 / `--toplevel` / `--path 9.502[24]` / `--find <数值>` / `--findstr <文本>` / `--ancestors` |
| `tools\patch-script.js` | 替换 `#50.1.5` Lua 源码（**默认不动 `.3` 文件名**，除非显式 `--file`） |
| `tools\extract-lua.js` | 把 `.gil` 里当前真正在跑的那份 Lua 抽出来核对 |
| `tools\ugc-diff.js` | 两个 `.gil` 差分 |

**注意**：`.gil` 的**探测偏移必须用可验证签名**，不要用启发式 —— 猜错过一次（18 vs 20），把用户的关卡写坏了。

### 10.2 屏幕与日志

- `tools\window-capture.ps1`
  - `-Hwnd <句柄>`（**新增**，多窗口进程必备：千星沙箱是一个进程里多个顶层窗口）
  - 枚举窗口的小技巧：`EnumWindows` + `GetWindowTextW` 能拿到真实标题（`MainWindowTitle` 在混淆窗口上可能是空的）
  - **PrintWindow 会抓到「停住不刷新」的旧画面**（对多面板 WPF 编辑器不可靠）；用户手机/电脑截图才是可信来源
- `Beyond_Debug_Log\*.gia` 是运行日志，但**不保证生成**（编辑器日志窗口在录制时才写）
- **最可靠的日志来源：让用户从编辑器「日志」窗口复制粘贴**

### 10.3 `ugc\luacheck\luacheck.js`（强烈建议保留）

fengari 驱动的 Lua 5.3 静态检查，四项：
1. 语法检查 + 生命周期回调清单
2. **大写常量：用了但没声明**（会静默 nil）
3. **前置声明检查：调用了后面才声明的局部函数**（新增，抓 §9.1）
   - 同时检测「同名 `local function` 多次声明 → 遮蔽前置声明」
4. 官方 API 名拼写抽查

用故意写坏的文件验证过：
```
❌ 前置声明问题（运行时会是全局 nil，函数中途报错）：
   baz()  在 L8 被调用，但直到 L10 才声明为 local
```

### 10.4 PowerShell 坑

- **PS 5.1 按 ANSI 读取 `.ps1`**：含中文的脚本**必须带 UTF-8 BOM**，否则注释解析报错
  （症状：`Missing expression after ','` 指向一个看起来完全正常的 `}`）
- 用 `powershell -ExecutionPolicy Bypass -File xxx.ps1` 绕过执行策略
- `foreach` 语句不能直接管道（`EmptyPipeElement`），先赋值给变量
- `Add-Type` 的 C# 代码不能引用 `System.Drawing.Point`，自己定义 struct

---

## 11. 官方文档与知识库

本地知识库取文档（10 篇客户端控件文档）：

```powershell
node tools\kb.js list                    # 列出全部文档
node tools\kb.js get "模板引用控件"        # 取正文
node tools\kb.js get "客户端控件容器"
```

10 篇：
```
按键提示控件 / 容器节点控件 / 客户端控件和客户端脚本 / 光标检测区域控件 /
预设按钮控件 / 网格视窗控件 / 客户端控件容器 / 客户端控件API文档 /
模板引用控件 / 文本视窗控件
```

节点目录（876 个节点 + 中文说明）：

```powershell
node tools\beyond-node-search.js --full "界面控件"
node tools\beyond-node-search.js --full "信号"
```

数据结构提示：`beyond-nodes.json` 里**出参在 `other.outParams`**，入参是顶层 `inParams`；额外配置字段（如「信号名」）在 `extraParamList`，要查 `beyond-textmap-chs.json` 里的
`BeyondEditorInstructionNodeConfig_extraParamList_0_name_<节点ID>`。

---

## 12. 标准作业流程（SOP）

### 12.1 从零做 2D 小游戏的清单

1. **先确认环境**：反向工程文件格式 → 找到 `external_lua_file` → 验证「改它 + 退进关卡」能生效（**这一步不验证，后面全是白干**）
2. **写探针脚本**：开机打印 `game.GetClientUIControl(1..80)` 的完整清单（类名/名字/prefabIndex/parent/子控件数）。**这是整个项目最有价值的一次输出**
3. **确认控件池够不够**，不够就开单给用户在画布上加控件（给准确路径 + Ctrl+C/V 技巧）
4. **先做可见性验证**：用池子里的控件画个大色块 + 一行字，确认「能拿到、能改、能显示」
5. **再定层级**（§6.5），把底板/棋盘/元素/文字/按钮排好
6. **再做交互**：键盘 + 全屏光标区域 + 坐标命中
7. **最后接节点图**：进入（`[307]` → `[384]` 显示 + `[300005]` 重开信号）、退出（`[300001]` → `[248]`+`[128]` → `[384]` 隐藏）
8. **状态机**：`ready`（等开始）→ `play` → `dead` → `exited`，退出后可重开

### 12.2 调试循环

```
改 external_lua_file\*.lua
  → 让用户「退出关卡 → 重新进入关卡」
  → 用户贴日志（或从编辑器日志窗口复制）
  → 分析
```
**一次迭代 ≈ 20 秒。** 所以：
- 一次把要看的诊断信息全打出来
- 日志分等级：正常信息用 `print`，异常用 `printerr`
- **不要在循环里刷屏**（曾经每帧刷错误日志，把有用信息冲没了）

### 12.3 与用户协作的要点

- 用户**只能手工操作编辑器**，任何编辑器操作都要给**逐级点选路径**，最好配「你截图我看」
- 每次让用户做实验前，**先说清楚预期看到什么**（哪个日志行 / 屏幕上什么现象）
- 用户说「不行」时，**先要日志**，不要猜
- 破坏性操作前**先备份**（`.gil` 尤其）

---

## 13. 复盘：这个项目走了哪些弯路（以及本可以怎么省）

| 弯路 | 根因 | 本可以 |
|---|---|---|
| 反复往 `.gil` 里塞脚本/控件，全被覆盖 | 不知道 `external_lua_file` 才是权威 | **第一步就该找「编辑器从哪读脚本」** |
| 花 8+ 轮试 `InstantiateClientUIControl` | 官方文档那句「存为模板」没读懂 | 一次性把「存为模板」试掉，或直接上控件池 |
| 「点了没反应」查了两轮 | `hideActionButton` 漏前置声明 | 有静态检查就不会有这轮 |
| 「蛇跑几步就坏」 | `destroySeg` 里先置 nil 再 `table.remove` | 数组改动只在一处做 |
| 「计数器没了」→「棋盘盖住蛇」 | `SetSiblingIndex` 的插入语义 | 递增游标一次定序 |
| 「节点参数设置错误」 | 实体 ≠ 玩家 的引脚类型 | 查节点目录时**同时查入参类型** |
| 光标残留 | 全局副作用放在了去重检查之前 | 副作用一律放最后 |

**最大的单点经验：先花 20 分钟确认「哪份文件是权威的、改完怎么生效」，再写一行游戏代码。**

---

## 14. 附：最终脚本骨架（贪吃蛇，约 1300 行 Lua）

文件：`E:\DSHworker\ugc\lua\snake.lua`（组件化结构，可直接改造成其它 2D 小游戏）

```
一、配置区          PREFAB_*（已弃用）/ 图片资源 ID / 信号名 / 开关
二、玩法参数        N=16 网格 / GOAL_BEANS / 速度曲线
三、颜色            COLOR_* 表
四、运行时状态      全局状态 + 前置声明区（★ 所有跨段引用都在这声明）
五、工具函数        rgba / setImgColor / setTxtColor
   方案B 控件池     scanPool / hideAllPool / hideAllUI / clearHostFlags
                    resetLayer / placeLayer / segSlots / acquireSegSlot
   setupImage / setupText
六、布局            layoutCanvas（按画布短边算 CELL/GRID）
七、HUD             refreshHUD（ready / play / dead 三种文本）
八、按钮 + 退出      setBlockGameInput / setShowCursor / clearHostFlags
                    onExitClicked / showExitButton
九、蛇              destroySeg / createSeg / spawnFood / newGame
                    die / tryReachGoal / step
十、开始 + 输入      hideActionButton / showActionButton / onAreaClick
                    startGame / showStartButton / enqueueDir
                    bindKeys / unbindKeys / onSwipeDown / onSwipeUp / bindSwipe
十一、生命周期       setupGame（= OnStart 主体，可重入）
                    OnStart / OnUpdate / OnEnable / OnDisable / OnDestroy
```

关键设计：
- `setupGame()` **可重入**，由 `OnStart` 和「SnakeReset 服务器信号」两条路调用
- 状态机 `phase`：`idle → ready → play → dead → exited →（重开）ready`
- **同一个按钮控件复用两次**：先「开始游戏」，点击后释放；后面再取出来当「退出游戏」
- 玩法参数集中在一处，方便改成别的游戏（推箱子/2048/扫雷都能复用同一套「控件池 + 层级 + 输入」骨架）

---

## 15. 【压轴】引擎会「销毁并重建客户端控件」—— 最后一个坑，也是最难查的一个

这是整个项目最后一个、也是最反直觉的 bug。**症状**：

> 玩过一次小游戏之后，**点某些（带传送功能的）选项卡，小游戏界面会自己蹦出来**；而**从没玩过**的时候，点同样的选项卡什么都不会发生。

### 15.1 现象与排除过程

先按直觉排查，全都排除掉了：

| 猜测 | 证据 | 结论 |
|---|---|---|
| `showCursor` / `disableKeyEventPassthrough` 没清干净 | 日志确认 `已清扫全部客户端控件的开关（清理 2 个）` | ❌ 不是 |
| `OnEnable` 里我加的「退出后自动重开」兜底 | 删掉后现象依旧 | ❌ 不是 |
| 节点图 `[307]` 没做条件筛选 | 加了 `事件源GUID == 选项卡GUID` 之后现象依旧 | ❌ 不是（但也确实该加） |
| 客户端收到了 `SnakeReset` | 日志里那一轮**完全没有** `收到服务器信号 SnakeReset` | ❌ 不是 |

### 15.2 日志里露出的马脚

把三轮对局的日志摊开看，每两轮之间都是这个形状：

```
（一轮结束）OnDisable ×2 → OnDestroy ×2          ← 客户端控件被销毁
（再进游戏）OnInit  ×2 → OnEnable ×2 → OnStart ×2 ← 控件被重新创建，脚本从零开始跑
```

**`OnInit` 再次出现 = 控件是新建的 = 引擎把整棵客户端控件树销毁重建了。**
而重建出来的控件会**按编辑器里的状态**（包括容器的显示状态）重新生效，于是 `OnStart` 一跑，`setupGame()` 就把界面建出来了。

**触发时机（实测）**：**传送 / 切换带传送功能的选项卡**、以及容器「隐藏 → 显示」的切换，都会让引擎重建客户端 UI。

### 15.3 真正的根因：容器被打开后再没关过

关键在「没运行过就不会」这句描述上：

| 状态 | 传送 → 引擎重建客户端控件 | 结果 |
|---|---|---|
| **没运行过**：容器还是「初始可见性 = 关」 | 重建出来的控件**不可见** | 什么都不出现 ✅ |
| **运行过一次后**：容器被 `[384] 显示状态=开启` 打开过，**而退出时没人把它关掉** | 重建出来的控件**可见** | `OnStart` → 界面自己冒出来 ❌ |

**结论一句话**：**「进入」和「退出」必须成对地把容器的显示状态开/关**。只做「按选项卡打开」不做「退出时关闭」，容器就永久停在显示状态，之后**任何一次引擎重建**都会把 2D 界面重新显示出来。

顺带解释了 §7.4 那个「退出后鼠标光标还在」：容器一直显示 → 控件一直活着 → 常驻光标一直挂着。**把容器真正关掉之后，光标也自然消失了（实测确认）。**

### 15.4 最终修法

在节点图里补上「退出 → 关闭容器」这条链（完整图见 §8.3）：

```
[300001] 监听信号 (SnakeExit)
   → [248] 获取在场玩家实体列表
   → [128] 获取列表对应值（序号 0）
   → [384] 设置界面控件(组)状态（索引 = 客户端控件容器，显示状态 = 关闭）
```

补上之后：**传送/切选项卡再也不会把小游戏带出来，鼠标光标也跟着消失。**

### 15.5 由此得到的通用规律（写给下一个人）

1. **客户端控件不是"一直在那儿"的东西** —— 引擎会在若干时机（传送、容器显隐切换、界面布局变化）**整棵销毁重建**，然后重新跑 `OnInit → OnEnable → OnStart`。
2. 所以 **`OnStart` 会在一次关卡游玩里被调用很多次**，你的脚本必须**可重入**（见 §9.5）。
3. **`OnStart` 不能当作「玩家想进游戏了」的信号** —— 它只代表"控件被创建出来了"。玩家意图要靠服务端事件（选项卡 / 信号）表达。
4. **容器打开和关闭必须成对**。`初始可见性=关` + 「按需打开」是对的，但**别忘了在退出时关上**。
5. **不要用固定范围的运行时 ID 去枚举控件** —— ID 全局递增且不复用，反复重建会让它一路涨（实测 `:1/:30` → `:31/:60` → `:61/:90`），
   固定扫 `1..80` 会漏掉后来的控件，症状是"池子越玩越小、按钮点不动"。
   **正确做法：`script.object:GetChildren()` 直接枚举画布根的子控件**（§6.2 已改成这样，只在枚举失败时才退回 ID 扫描）。
6. **服务端发给客户端的信号可能在"控件刚重建"的瞬间丢失**（新实例还没注册监听，信号已经发走了）。
   → 关键流程不能只靠信号，要有「引擎重建 → `OnStart`」这条天然路径兜底。

### 15.6 一句话总结这个项目

> **能做**：用「控件池 + 层级 + 坐标命中」在千星奇域里做完整 2D 小游戏，脚本迭代 20 秒一轮，无需重启编辑器。
> **最容易翻车的三件事**：① 改错文件（`.gil` 会被覆盖，要改 `external_lua_file\*.lua`）；
> ② `SetSiblingIndex` 的插入语义（会挤动后面的控件）；
> ③ **忘了成对开关客户端控件容器**（引擎重建时会自己蹦出界面）。


# 千星奇域 2D 小游戏开发 Skill（v1.0）

> 面向 AI Agent。目标：让一个**从未接触过千星奇域**的 Agent，在几小时内做出可玩的 2D 小游戏
> （像素画 / 华容道 / 贪吃蛇 / 2048 / 推箱子 …），并**避开前人踩过的全部坑**。
>
> 本 skill 综合自三份实战文档：
> - 2026-10-07 贪吃蛇项目（控件池 + 服务端节点图）
> - 2026-10-12/13 图片华容道项目（动态创建 + 160×160 / 200×200 真彩像素渲染）
> - 2026-10-13 场景图片压缩方案（RLE 色块 / 跨关卡复制）
>
> 标注约定：**【实测】** = 在日志或画面上验证过；**【推断】** = 有证据未直接验证；**【未解】** = 尚未搞明白。

---

## 0. 执行约束（写给 Agent）

### 0.1 你必须在第一次回复中就告诉用户"你能做什么"

**这是硬要求。** 在用户提出需求后、动手之前，你必须先用一段话说明：

1. **整体能力**：你能在这个引擎里做出完整的 2D 小游戏（有哪些类型、能到什么精度）
2. **本次能做到什么**：针对用户的具体需求，给出**可执行的方案 + 预估耗时 + 需要用户配合的手工操作数量**
3. **需要用户做什么**：编辑器操作（只能人工）、试玩、贴日志——每步都说清"你会看到什么"

**不要**直接开始写代码。用户需要先知道这次协作的形态。

### 0.2 三个绝对不能违反的约束

| # | 约束 | 违反后果 |
|---|---|---|
| 1 | **只改 `external_lua_file\<名字>.lua`**，绝不改 `.gil` | 编辑器进关卡时整份重写 `.gil`，你写的东西全丢 |
| 2 | **改完必须让用户"退出关卡 → 重新进入关卡"** | 脚本不生效，你会误判成"代码有 bug" |
| 3 | **所有控件必须在同一帧内一次性建完**，不要跨帧分批 | 跨帧创建慢 20 倍，且极易触发引擎保护 |

### 0.3 你的迭代节奏

```
改 lua → 用户退出关卡 → 用户进关卡（约 20 秒）→ 用户贴日志 → 分析
```

**一次迭代只有 20 秒**，所以：
- **一次把诊断信息打全**（不要"改一次日志、再跑一次"）
- 每个实验前**先说清预期看到什么**（哪行日志 / 屏幕什么现象）
- 用户说"不行"时**先要日志**，再分析，不要猜
- **用户的主观描述是一等证据**（实战中用户说"仅 y 上出错""参考图正常"都直接指对了方向）

---

## 1. 能力披露（给用户看的）

### 1.1 你能做什么

| 能力 | 说明 | 可靠性 |
|---|---|---|
| 客户端脚本全自动生成 | Lua 5.3，含生命周期、输入、渲染、状态机 | ✅ 成熟 |
| **像素画渲染** | 用 N×N 个控件拼出一张真彩（1670 万色）图 | ✅ 成熟，有实测上限 |
| **图像动态变换** | 拼图/推箱子/华容道（块移动）、贪吃蛇（逐帧重绘） | ✅ 成熟 |
| 键盘输入 | 方向键、WASD、功能键（P/J/K/L/V/F5…） | ✅ 成熟 |
| 鼠标输入 | 点击、拖拽滑动、命中判定 | ✅ 成熟（需用户建"光标检测区域"） |
| 文字显示 | 文本框控件，可做 HUD / 计分 / 按钮文字 | ✅ 成熟 |
| 服务端联动 | 选项卡进入、信号收发、容器显隐 | ✅ 成熟（贪吃蛇已验证） |
| 一键部署脚本 | 免去手工找路径、防编辑器覆盖 | ✅ 已提供 |
| 离线模拟验证 | 用 fengari 在 Node 里跑 Lua 逻辑 | ✅ 成熟 |

### 1.2 你不能做什么（**必须诚实告知用户**）

| 限制 | 原因 | 替代方案 |
|---|---|---|
| ❌ **不能自动化编辑器** | 内核级反作弊，UI 树不暴露 | 给用户**逐级点选路径**，用户手工做（约 1~3 分钟） |
| ❌ **不能改 `.gil` 里的控件布局** | 编辑器会整份重写 | 只能读 `.gil` 分析，然后指导用户在编辑器操作 |
| ❌ **不能上传自定义图片资源** | 无权限 | 用"像素画"（N×N 色块）替代；或仅用内置图 `100001`/`106011` |
| ❌ **不能做到像素完美（零摩尔纹）** | 画布→物理缩放 `s ≈ 1.07~1.14` 非整数 | 接受轻微摩尔纹；或降低像素数（详见 §7.4） |
| ⚠️ **控件数有硬上限** | 实测：51,664 稳定 / 61,440 崩 | 控制在 **52,000 以内** |
| ⚠️ **分辨率有实际上限** | 控件数 ÷ 参考图控件数 = 棋盘可用控件数 | 200×200 是实测最高可用 |

### 1.3 精度 ↔ 耗时对照（**必须给用户这张表**）

用户在提需求时通常会说"我要高清"，你需要把它翻译成**具体像素网格**并告知代价：

| 棋盘精度 | 每格 | 棋盘控件 | +108×108参考图 | 总计 | 构建耗时 | 观感 |
|---|---|---|---|---|---|---|
| 96×96 | 24×24 | 9,216 | 11,664 | 20,880 | **≈ 5.6 s** | 明显像素感 |
| 128×128 | 32×32 | 16,384 | 11,664 | 28,048 | **≈ 8.0 s** | 清晰，像素感适中 |
| 160×160 | 40×40 | 25,600 | 11,664 | 37,264 | **≈ 11.2 s** | 清晰（推荐） |
| 200×200 | 50×50 | 37,500 | 11,664 | 51,664 | **≈ 17.6 s** | 很清晰（**仍可 OnStart 一次建完**） |
| 256×256 | 64×64 | 61,440 | — | 61,440 | **≈ 26 s → 会被看门狗中断** ❌ | 需分帧创建 ✅ |
| 300×300 全屏图 | — | — | — | ≈ 8 万 | 单次 ❌ / **分帧 ≈ 60~90 s** ✅ | 很精细 |
| 600×600 全屏图 | — | — | — | ≈ 10 万 | 单次 ❌ / **分帧 ≈ 2~3 分钟** ✅ | 极精细 |

**耗时公式（实测拟合，含退化项）**：

```python
# 每控件耗时随"已有控件数"线性上升（引擎内部全局开销，无法规避）
单次建完总耗时(秒) = (0.27 * N + 3.75e-6 * N * N) / 1000
#   N=10,000 → 3.1 s    N=20,000 → 7.1 s    N=50,000 → 22.9 s（≈单次回调上限）
#   N=100,000 → 27 + 37 = 64 s（单次必被中断 ✗，必须分帧）

# 分帧创建（默认 40 ms/帧）：每帧开销还有引擎遍历成本 ≈ 1.7 µs × 已建控件数（隐藏态）
#   → 总时间略高于单次，但【全程无长冻结】，且不受看门狗限制 ✓
```

> **★ 决策阈值 50,000 个控件**：
> **≤ 50,000 → 推荐 OnStart 一次建完** ✓（更快更简单）；
> **> 50,000 → 必须分帧创建** ✓ —— 方法与完整代码见 `examples/大批量控件-分帧创建.md`。
**画质建议**：
- 每个逻辑像素屏幕上占 **≥ 6 物理点**时观感可接受（`每逻辑像素物理点 = CELL × 1.1`）
- 若用户嫌糊 → **降像素数**（不是提高像素数！提高像素数会让每个像素占的物理点变少，反而更糊）
- **这条反直觉，务必写进对用户的解释里**

---

## 2. 环境与文件布局

### 2.1 关键路径

```
%USERPROFILE%\AppData\LocalLow\miHoYo\原神\BeyondLocal\<UID>\
  Beyond_Local_Save_Level\<关卡ID>\
      <关卡ID>.gil                      ← 编辑器整份副本（★ 别改）
      external_lua_file\<脚本名>.lua     ← ★ 权威脚本源码（只改这个）
  Temp\<关卡ID>.gil                      ← 工作副本
  Beyond_Debug_Log\*.gia                 ← 运行日志（不一定生成，但常能读到）
```

**找 UID**：`BeyondLocal\` 下的数字目录（如 `342243974`）。

### 2.2 `.gil` 格式（只读分析用）

```
[20 字节头] + [明文 protobuf] + [4 字节尾]      ← 无加密
头部 = 5 个大端 u32：head[0] = 总长-4，head[4] = 总长-24
```

**⚠️ 解析必须用可验证签名**（`u32@0 == total-4` 且 `u32@(N-4) == total-4-N`），
**不要用启发式猜偏移**——曾猜错成 18 而非 20，把用户的关卡文件写坏过。

关键字段：

| 路径 | 含义 |
|---|---|
| `#1` / `#2` | 关卡 ID / 名称 |
| `#9.502[i]` | 第 i 个界面控件组 |
| `#9.502[i].501` | 控件组 ID（= 运行时 `prefabIndex`） |
| `#9.502[i].504` | 继承的模板 ID（无 504 = 根组） |
| `#9.502[容器].505[3].503.73.501` | 客户端控件容器的「画布根控件组 ID」 |
| `#50.1.1/.2/.3/.5` | 脚本映射 ID / 脚本名 / **文件名** / Lua 源码 |

### 2.3 一键部署（免去手工找路径）

```powershell
# 把脚本拖到 tools\deploy.bat 上，或：
tools\deploy.bat 你的脚本.lua [关卡ID]
```

它会：自动找 UID → 匹配关卡里已有的 `.lua` 文件名 → 备份 → 复制 → **校验哈希**。

**⚠️ 文件名必须与 `#50.1.3` 完全一致**，否则编辑器报「引用丢失 xxx.lua」。
deploy.bat 会自动沿用关卡里已有的文件名，所以通常不用管。

### 2.4 紧急止血

关卡一进去就卡死 / 无限重建时：

```powershell
tools\kill.bat [关卡ID]
```

把脚本换成空脚本（`.gil` 完全不动），即可安全进关卡。

---

## 3. 系统模型（必须先理解的三层）

```
【服务器控件层】
    客户端控件容器（ClientUIContainerControl）
      │  ← 这是"服务器控件"，负责把客户端 UI 显示到主屏
      │  ← 有开关：showCursor / disableKeyEventPassthrough
      ↓
【客户端画布层】
    画布根（容器引用的那个控件组）
      └─ 子控件：图片 / 文本框 / 光标检测区域
                    ↑
                    └── ★ 脚本挂在这里（不是画布根本身！）
      ↓
【动态实例化层】
    ClientUIPrototypeHierarchyRoot (1073741844)
      ├─ 1073741931  图片        ← 「已存为模板」才可实例化
      ├─ 1073741927  文本框
      ├─ 1073741928  光标检测区域
      └─ ...
```

### 3.1 三种"控件"的区别（务必分清）

| 概念 | 是什么 | 能否动态实例化 |
|---|---|---|
| **界面控件组** | `.gil` 里 `#9.502` 的一个条目 | ❌ 画布上普通摆放的不能 |
| **客户端控件模板** | 「存为模板」过的客户端控件 | ✅ **只有这种能** |
| **客户端控件容器** | 服务器控件，负责把 UI 显示出来 | —— |

**实测**：`game.InstantiateClientUIControl(模板ID, 画布根的子控件)` 才能成功；
宿主给「画布根本身」→ **全部返回 `nil`**（前作曾因此得出"此 API 不可用"的错误结论）。

---

## 4. 从零开始的 SOP（14 步）

```
 1. 找环境        → 定位 external_lua_file，确认 UID 与关卡 ID
 2. 问清楚需求    → 游戏类型 / 精度 / 是否需要参考图 / 是否需要鼠标
 3. 给能力与代价  → 用 §1.3 的表格告诉用户精度↔耗时，让用户选
 4. 指导建模板    → 用户手工在编辑器建「图片/文本框/光标检测区域」并「存为模板」
                    （或者直接导入模板 .gil，见 §5）
 5. 写探针脚本    → ★ 部署探针，列可用模板 + 类名 + 宿主；这一步不通过后面全是猜
 6. 布局计算      → 画布尺寸、CELL、棋盘/参考图位置、控件总数（< 52,000）
 7. 生成图像数据  → 真彩 RLE + ★ 生成器自检（块内单色 / 长度）
 8. 离线模拟      → fengari 内联加载，验证逻辑（移动、不变量、解算）
 9. 一次性建+画   → 建控件时直接设最终颜色（★ 不二次改色）
10. 输入绑定      → 键盘 + 光标（先设 showCursor）+ 固定角色
11. 移动重画      → 只重画源格 + 目标格；每次移动后查不变量
12. 加固          → 硬校验数据长度、pcall + printerr 堆栈、脚本可重入
13. 交付          → 记下实际配置与耗时；写一份玩法说明给用户
14. 更新本文      → 把新的实测数字 / 新踩的坑写回本文件
```

---

## 5. 模板 `.gil` 的导入与使用

### 5.1 本 skill 提供的模板

`templates\2D-ready.gil` —— 一个**已经配置好全部必需模板**的 2D 关卡。
导入后你只需要改脚本，不必让用户手工建模板。

**它包含**（用 `probe-gil.js --ui` 可验证）：

```
[ 0]  1073741931   图片               ← ★ 图片模板（像素画/色块/按钮底）
[16]  1073741845   客户端控件容器        ← 容器（提供 showCursor 等开关）
[24]  1073741928   光标检测区域         ← ★ 鼠标事件
[25]  1073741927   文本框             ← ★ 文字 / HUD / 按钮字
[26]  1073741926   图片
[28]  1073741932   光标检测区域
```

### 5.2 导入步骤（用户手工）

```
1. 备份自己关卡目录下的 <关卡ID>.gil
2. 把 templates\2D-ready.gil 复制到
   …\BeyondLocal\<UID>\Beyond_Local_Save_Level\<你的关卡ID>\
   并改名为 <你的关卡ID>.gil
3. 用编辑器打开该关卡 → 检查「界面控件组管理」里能看到上述模板
4. 若要用脚本：在画布上选中一个控件 → 挂载客户端脚本 → 脚本名与
   external_lua_file 下的文件名一致
```

**⚠️ 编辑器会重写 `.gil`**，所以导入后**不要指望 `.gil` 保持原样** —— 这是正常的。
模板只要导入成功，就会被编辑器接管。

### 5.3 如果不想导入模板（手工建）

给用户的**逐级点选路径（一字不差地照抄给用户）**：

```
界面控件组管理 → 界面布局 → 布局详情/自定义 → 点「客户端控件容器」
  → 右侧「画布设置」→【前往编辑】
  → 左下角【添加控件】→ 选「图片」/「文本框」/「光标检测区域」
  → 更快：选中已有控件 Ctrl+C / Ctrl+V
  → 然后选中它 → 点底部/右键的【存为模板】  ← ★ 关键，不做这步无法动态实例化
```

### 5.4 模板 ID 会变 → 必须自动探测

模板被删除重建后 ID 会变。**不要写死**，用探测：

```lua
-- 原理：用不存在的 ID 调 InstantiateClientUIControl 只是返回 nil，代价极小
local function discoverTemplate(wantClass)
    local prio = { 1073741931, 1073741926, 1073758498, 1073758497 }
    local function ok(id)
        local o, c = pcall(game.InstantiateClientUIControl, id, host)
        if o and c ~= nil then
            local cls = tostring(c)
            pcall(game.DestroyClientUIControl, c)
            -- ★ 必须验证类名！否则可能扫到"不是图片控件"的模板
            if not wantClass or string.find(cls, wantClass, 1, true) then
                return true, cls
            end
        end
        return false
    end
    for i = 1, #prio do
        local f, cls = ok(prio[i]); if f then return prio[i], cls, "候选" end
    end
    local ranges = { {1073741800, 1073742100}, {1073758300, 1073759000} }
    for r = 1, #ranges do
        for id = ranges[r][1], ranges[r][2] do
            local f, cls = ok(id); if f then return id, cls, "扫描" end
        end
    end
    return nil, nil, "失败"
end

-- 用法
local TPL_IMG, cls = discoverTemplate("ClientUIImageControl")
local TPL_TXT     = discoverTemplate("ClientUITextBoxControl")
local TPL_AREA    = discoverTemplate("ClientUICursorEventAreaControl")
```

**⚠️ 只判断"能实例化"是不够的** —— 曾扫到非图片控件，渲染成白方块且忽略 `SetImage`。

---

## 6. 坐标系统（**最容易出错的地方**）

### 6.1 三个坐标系

| 名称 | 原点 | 说明 |
|---|---|---|
| **画布单位** | 中心 | `game.GetUICanvasSize()` → 实测 `1599 × 899`（可能带小数，取整） |
| **控件坐标** | 父控件中心 | `SetAnchoredPosition(x, y)`；**y 向上为正** |
| **光标 UI 坐标** | **画布左下角** | `data:GetUIPos()`；**y 向上为正** |

### 6.2 换算式

```lua
-- 光标坐标 → 控件坐标
local W, H = game.GetUICanvasSize()
local cx, cy = x - W * 0.5, y - H * 0.5
```

**★ 但实战中我们踩过坑：** 如果游戏逻辑的 y 向上、而你想"点屏幕上方 = 逻辑上方"，
在部分环境里仍需要翻转：

```lua
playCellAt(x - W * 0.5, H * 0.5 - y)     -- 翻转 y（华容道项目实测需要）
```

**结论：不要推理，实测确认。** 做法：让用户点一个已知位置，把 `(x, y)` 打进日志，与预期对比。

### 6.3 像素格布局（正确的画布→控件映射）

```lua
-- 把 PW×PW 的像素网格铺在画布上
local half = (PW - 1) * 0.5
for py = 1, PW do
    for px = 1, PW do
        local ctl = newBlock(color, CELL)
        ctl:SetAnchoredPosition(
            BOARD_X + (px - 1 - half) * CELL,     -- x：左→右
            BOARD_Y + (half - (py - 1)) * CELL)   -- ★ y：用 (half - …)，因为第 1 行在最上
    end
end
```

**实测坐标自检**（强烈建议每次都打）：

```
格  1 (r1c1) 中心 = (-470, 298)     ← 第 1 行：y 最大
格 16 (r4c4) 中心 = ( 130, -302)    ← 第 4 行：y 最小
```

如果第 1 行的 y 不是最大 → **你的 y 轴方向搞反了**。

---

## 7. 像素渲染架构

### 7.1 核心思路

```
一张图 = N×N 个控件，每个控件 = 1 个逻辑像素
每个控件：SetSizeDelta(CELL + OVERLAP*2)  → 相邻控件略微重叠，消除细缝
每个控件：imageColor = Color.FromRGBA(r,g,b,255)  → 24 位真彩
```

### 7.2 创建控件的正确写法

```lua
local function newBlock(color, size)
    local ctl = game.InstantiateClientUIControl(TEMPLATE, host)
    if ctl == nil then return nil end
    ctl:SetAnchorMin(0.5, 0.5)
    ctl:SetAnchorMax(0.5, 0.5)
    ctl:SetPivot(0.5, 0.5)
    ctl:SetSizeDelta(size + OVERLAP * 2, size + OVERLAP * 2)
    ctl.SetImage(ctl, Enum.ImageSource.StaticReference, 100001)   -- 内置直角白图
    ctl.imageType = Enum.ImageType.Stretch
    if color then
        ctl.imageColor = Color.FromRGBA(color[1], color[2], color[3], 255)
    end
    return ctl
end
```

内置图片资源：`100001`（直角白图）、`106011`（圆角白图）。

### 7.3 ★★★ 数据索引约定（**整个项目最大的坑**）

**数据必须是「整幅 PW×PW 行主序」**：

```
数据索引（1-based）= y * PW + x + 1          （x, y 为整图坐标，0-based）
```

**把画布切成 4×4 块时**（K = PW/4）：

```
块 d（0-based）的格内像素 (bx, by) 在整图中的位置：
    gy = d // 4      gx = d % 4
    全局 y = gy*K + by      全局 x = gx*K + bx
    数据索引 = (gy*K + by) * PW + (gx*K + bx) + 1
```

**❌ 错误写法（前人写了十几轮）**：

```lua
-- 把块 d 当成数据里的连续段 [d*K*K, (d+1)*K*K)
col = pix[(d-1)*K*K + by*K + bx + 1]
```

**为什么错**：`by` 方向步长用了 `K`（如 32），而**整幅图的行宽是 `PW`**（如 160）。
后果：块内第 2 行起就读到别的块 → **块内出现横条**；
而 **X 方向恰好正确**（`+bx` 在两种解释下数值相同）→ 症状是「**只有 Y 方向错**」。

**★ 必须写进生成器的自检**：

```python
# 生成后立即断言：每个块内部颜色种类必须为 1
for d in range(16):
    gy, gx = d // 4, d % 4
    reg = set(px[(gy*K+by)*PW + (gx*K+bx)] for by in range(K) for bx in range(K))
    assert len(reg) == 1, f'块 {d+1} 内部多色 → 索引约定不一致！'
```

**这条自检能省 10 轮往返。**

### 7.4 画布→物理缩放与摩尔纹（**诚实告知用户**）

- 实测 `s ≈ 1.07 ~ 1.14`（1 画布单位 ≈ 1.1 物理像素），**非整数**
- 所以每个逻辑像素覆盖**非整数**物理像素 → **必然存在混叠**
- **精度误差** `ε = frac(CELL × s)`，`ε = 0.5` 时最差
- **反直觉结论**：
  - **增加像素数会让画面更糊**（每个像素占的物理点变少 → 混叠更明显）
  - **减少像素数反而更清晰**（每个像素占更多物理点）
- 经验阈值：每逻辑像素 **≥ 6 物理点**时观感可接受
- **不要试图靠"调整间距"消除**：修正量被量化到整数画布单位，数学上闭合不了
- **要真正像素完美**只有两条路：① 改画布分辨率使 `s` 为整数；② 一个控件承载一整块图（需传资源）

### 7.5 「一次画到位」vs「先建后重绘」★

| 做法 | 结果 |
|---|---|
| 建控件时**直接设最终颜色**（每控件只写一次） | ✅ 干净 |
| 先建 + 之后 `redrawAll()` 改一遍颜色 | ❌ **条纹**（引擎对同一控件二次改色有采样痕迹） |

**所以**：初始状态的颜色必须在创建时算好（把游戏状态直接算进取色索引），
**不要事后重绘全盘**。移动时才对**受影响的格子**重画。

### 7.6 空洞 / 占位的正确表示

```lua
-- ❌ 错误：HOLE_TAG = 16 不是 nil，if d then 会把它当有效块
if d then col = pixels[...] else col = HOLE_COLOR end

-- ✅ 正确
if d and d ~= HOLE_TAG then col = pixels[...] else col = HOLE_COLOR end
```

**后果**：空洞格被画成"最后一块"的内容，而**真正属于该格的那块永不显示** → **整幅图错位一格**。

### 7.7 取色必须用「块自身」的位置

```lua
-- ❌ 用目标格的位置取色（gy/gx 是目标格）
col = pixels[(gy*K + by) * PW + (gx*K + bx) + 1]

-- ✅ 用块自身在整图中的格位置
local dgy, dgx = (d-1) // 4, (d-1) % 4
col = pixels[(dgy*K + by) * PW + (dgx*K + bx) + 1]
```

**目标态下两者相同**，所以不打乱时不会暴露；**打乱后必错**。

### 7.8 移动后必须重画两格

```lua
local function applyMove(d, fromG, toG)
    cellPiece[fromG], cellPiece[toG] = HOLE_TAG, d
    pieceCell[d], pieceCell[HOLE_TAG] = toG, fromG
    paintCell(fromG)      -- ★ 源格：现在变空，涂空洞色
    paintCell(toG)        -- ★ 目标格：现在有块
end
```

只重画目标格 → **源格残留旧图**（看起来像块被复制了一份）。

---

## 8. 图像数据管线

### 8.1 真彩 RLE 格式

```
每 4 字节一组： [R][G][B][run]        run = 1..255
Lua 里存成 hex 字符串
```

```lua
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
```

### 8.2 ★ 硬校验（防止"空数据静默通过"）

```lua
local bpix = unpackTruecolor(PIXEL.RGB, PW * PW)
if #bpix ~= PW * PW then
    err(string.format("!! 数据长度 %d != 期望 %d，终止", #bpix, PW * PW))
    return
end
```

**为什么必须**：防御式写法 `if color then ctl.imageColor = ... end`
会让**空数据被静默当成"没有颜色"** → 全部控件保持默认白色 → 屏幕一片白，极难排查。

### 8.3 调色板 vs 真彩

| 方案 | 颜色数 | 数据量 | 适用 |
|---|---|---|---|
| **调色板索引**（1 字节） | ≤ 256 色 | 小 | 像素画 / 平涂场景 |
| **真彩直传** | 1670 万色 | 大（RLE 后 95~146 KB / 160~200²） | 照片 / 插画 |

**不传资源的唯一高清路线 = 真彩**。实测一张插画用 12,993 色。

### 8.4 生成器（Python）参考

```python
from PIL import Image
import numpy as np

def rle_truecolor(img, pw):
    a = np.asarray(img.resize((pw, pw), Image.LANCZOS).convert('RGB'))
    flat = a.reshape(-1, 3)
    out = bytearray()
    i, n = 0, len(flat)
    while i < n:
        r, g, b = flat[i]
        run = 1
        while i+run < n and run < 255 and tuple(flat[i+run]) == (r, g, b):
            run += 1
        out += bytes([r, g, b, run])
        i += run
    return bytes(out).hex()

# ★ 生成后自检
def selfcheck(flat, pw, nblocks=4):
    K = pw // nblocks
    for d in range(nblocks*nblocks):
        gy, gx = d // nblocks, d % nblocks
        for by in range(K):
            for bx in range(K):
                idx = (gy*K+by)*pw + (gx*K+bx)
                assert 0 <= idx < len(flat), '索引越界'
    print('自检通过')
```

---

## 9. 性能模型与上限

> ★ **要建超过 5 万个控件，必读** `examples/大批量控件-分帧创建.md`（含可直接抄的代码）。
> 本节给结论，那篇给完整方法与踩坑记录。

### 9.1 创建控件的成本 【实测·2026-10 修订】

| 操作 | 实测耗时 | 复杂度 |
|---|---|---|
| **创建一个控件** | **0.27 ~ 1.26 ms/个**（随已有控件数上升） | **T = 0.27N + 3.75e-6·N²** |
| 改一个控件的颜色 | 0.004 ~ 0.007 ms/次 | ∝ 改色次数 |
| 纯 Lua 计算（索引/查表/判断） | 纳秒级 | 可忽略 |

```
每控件耗时 = 0.27 + 3.75e-6 × 已有控件数   (ms)          ← ★ 这个退化项是引擎内部的
总耗时     T ≈ 0.27·N + 3.75e-6·N²          (ms)
```

| N | 实测每控件 | 实测总耗时 |
|---|---|---|
| 5,000 | 0.270 ms | 1.35 s |
| 10,000 | 0.271 ms | 2.71 s |
| 20,000 | 0.403 ms | 8.06 s |
| 132,000 | 1.258 ms | 166 s |

**已实测排除的"加速"思路（别再试）**：
- ✗ **分块挂载**（多个父节点）：退化曲线**完全不变**（把 16.8 万控件分 12 组、每组 1.4 万，曲线一样）
- ✗ **加大每帧批量**：只快约 **1.4 倍**（不是 3~5 倍），因为主导项与批量无关
- ✗ **控件复制 API**：`CloneClientUIControl` / `c:Clone()` / `c:Copy()` 等 **9 种全部不存在**
- ✗ **预配置模板/去掉 pcall**：最多约 10%（0.27 ms 里 0.24 ms 是引擎 Instantiate 本身）

**推论**：`0.27·N` 是理论下界 → 16.8 万个控件**至少 45 秒**，不可能更快。

### 9.2 每帧渲染成本 【实测】★ 这才是真正的天花板

```
每帧耗时 ≈ 15~18 µs × 【可见】控件数        ← 严格线性
```

| 可见控件数 | 实测帧时间 | 帧率 |
|---|---|---|
| 5,000 | 80.9 ms | 12 fps |
| 10,000 | 150.4 ms | 7 fps |
| 20,000 | 300.8 ms | 3 fps |
| 90,000 | 1,760 ms | 0.6 fps |

**隐藏态便宜约 9 倍**，而"隐藏 → 显示"这个转换会让引擎重建高效渲染批次：

| 20,000 个控件的状态 | 每帧耗时 | 每控件 |
|---|---|---|
| 可见 | 300.8 ms | 15.0 µs |
| 隐藏 | 33.2 ms | 1.7 µs |
| **隐藏建立 → `SetVisible(true)`** | **35.3 ms** | **1.8 µs** ✓✓ |

### 9.3 控件数上限 【实测·已修订】

| 控件数 | 单次回调（OnStart）建完 | **分帧创建** |
|---|---|---|
| 37,264 | ✅ 稳定 | ✅ |
| **50,000** | ✅ **实测正常（约 22 s）—— 单次回调的推荐上限** | ✅ |
| 61,440 | ❌ 会被看门狗中断 | ✅ |
| 90,000 | ❌ | ✅ **稳定** |
| **100,000** | ❌ | ✅ **稳定（实测）** |
| 167,915 | ❌ | ✅ 能建成（约 3 分钟） |

```
★ 决策阈值：【50,000 个控件】

   控件数 ≤ 50,000  →  ★ 推荐 OnStart 单次回调创建 ✓✓
                        更快（少控件时比分帧快 34%）、代码最简单、无需状态机
   控件数 >  50,000  →  必须分帧创建 ✓（见 9.4）

   实测 20,000 个：OnStart 单次 8.06 s  vs  分帧隐藏 10.78 s → 单次反而更快 ✓

★ 没有"控件数硬上限"，只有【单次回调时长上限】（约 22 秒）
```

**不同分辨率下的可行规模**（动态 STD 默认开启时）：

| 分辨率 | 块数 | OnStart 单次 | 分帧(40ms/帧) |
|---|---|---|---|
| 160×160 | ≈ 2.6 万 | ≈ 11 s ✅ **推荐** | — |
| 200×200 | ≈ 3.6 万 | ≈ 17 s ✅ **推荐** | — |
| 300×300 | ≈ 8 万 | 超时 ❌ | ≈ 60~90 s ✅ |
| 600×600 | ≈ 10 万 | 超时 ❌ | ≈ 2~3 分钟 ✅ |

### 9.4 ★ 分帧创建（**仅当控件数 > 50,000**）

> ≤50,000 个控件请直接用 **OnStart 一次建完** ✓（更快更简单，本节可跳过）

四个要点（**完整代码见 `examples/大批量控件-分帧创建.md`**）：

```
① 解析/解码数据也要分帧   —— 一次性解析大数据 = 被看门狗【静默截断】
                              （实测 167,915 块被截在 132,000，表现为"图像下方少一条"）
② 建立时全程隐藏          —— 每帧 1.7 µs/个，而不是 15 µs/个
③ 建完 SetVisible(true)   —— 这一次转换换来约 9 倍帧率
④ 显示也要分帧            —— 一次显示 10 万个会卡死一帧；分成 K 组每帧显示一组

★ 显示/隐藏必须用冒号调用：c:SetVisible(false) / c:SetActive(false)
  ✗ 点号赋值 c.visible = false 会失败（且被 pcall 吞掉，静默无效）
```

**默认每帧预算 40 ms**（平滑，用户只见画面逐步长出；提到 120 ms 只快 1.4 倍且会顿）。
**进度标签必须挂在根下**（挂在被隐藏的组里会看不见 ✗）。

### 9.5 崩溃的表现与止血

```
现象 A（看门狗中断）：日志 "Lua execution took too long" + traceback，
                      脚本被截断（如数据只解析了一部分），画面缺一块
现象 B（旧版一次建太多）：构建完成后立刻 OnDestroy → OnStart → 无限循环，卡死
```

**止血**：用 `tools\kill.bat` 把脚本换成空脚本（`.gil` 不用动）。

### 9.4 同色游程压缩（可选优化，**只对静态场景有意义**）

对**平涂像素画**，合并"水平连续同色"为 1 个控件（宽度 = 游程长度）：

| 配置 | 像素 | 游程数 | 创建耗时 |
|---|---|---|---|
| 320×180 逐像素 | 57,600 | 57,600 | ≈ 20.2 s |
| 320×180 / 26 色 RLE | 57,600 | ~22,000 | ≈ 7.8 s |
| 160×90 / 26 色 RLE | 14,400 | ~6,900 | ≈ 2.4 s |

**⚠️ 重要澄清**：RLE 只减少"创建耗时"，**不减少"渲染/重绘耗时"**
（因为覆盖的像素总数没变）。所以：
- **静态背景** → RLE 非常划算
- **可移动的块**（拼图/贪吃蛇） → RLE 帮助有限，且会让移动后的重绘逻辑复杂得多

---

## 10. 输入系统

### 10.1 ★ 权威按键表（来自官方 API 文档）

| 枚举名 | 物理键 |
|---|---|
| `KeyboardCraftspersonKey36Down` | **↑** |
| `KeyboardCraftspersonKey37Down` | **↓** |
| `KeyboardCraftspersonKey38Down` | **←** |
| `KeyboardCraftspersonKey39Down` | **→** |
| `KeyboardCraftspersonKey18Down` | **P** |
| `KeyboardCraftspersonKey19~22Down` | J / K / L / V |
| `KeyboardCraftspersonKey23~28Down` | F5 / F6 / F7 / F8 / F9 / F10 |
| `KeyboardMoveForwardKeyDown` | **W** |
| `KeyboardMoveBackwardKeyDown` | **S** |
| `KeyboardMoveLeftKeyDown` | **A** |
| `KeyboardMoveRightKeyDown` | **D** |
| `ControllerMenuBackKeyDown` | 手柄返回 |

**⚠️ 没有 R 键、没有 Esc**（`CharacterSkill3Key` 才是 R，但拿不到 `KeyNN` 形式）。

**枚举存在的键**（实测可用）：`Key18`~`Key41`、四个方向键、四个 WASD、`ControllerMenuBackKeyDown`。

### 10.2 键盘绑定

```lua
local target = script.object      -- 就是 ClientUIContainerControl
target:AddKeyEventListener(Enum.KeyEventType.KeyboardMoveForwardKeyDown, function()
    doAction()      -- 你的逻辑
    return true     -- ★ 返回 true 吞掉事件（否则可能传给 3D 角色）
end)
```

### 10.3 ★ 方向映射：必须实测，不要推理

不同游戏对"方向"的语义不同（"块朝按键方向滑" vs "把该方向的块推过来"），
而且**键位 ↔ 方向的对应很容易反**。

**推荐做法：做成运行时可切换 + 让用户实测选定。**

```lua
-- 键 → 逻辑方向（1上 2下 3左 4右）
local keyToDir = {
    KeyboardCraftspersonKey36Down = 1,   -- ↑
    KeyboardCraftspersonKey37Down = 2,   -- ↓
    KeyboardCraftspersonKey38Down = 3,   -- ←
    KeyboardCraftspersonKey39Down = 4,   -- →
    KeyboardMoveForwardKeyDown    = 1,   -- W
    KeyboardMoveBackwardKeyDown   = 2,   -- S
    KeyboardMoveLeftKeyDown       = 3,   -- A
    KeyboardMoveRightKeyDown      = 4,   -- D
}
-- 变换模式（可运行时切换）：1 原样 / 2 上下翻 / 3 左右翻 / 4 都翻
local MODES = { {1,2,3,4}, {2,1,3,4}, {1,2,4,3}, {2,1,4,3} }
```

**让用户按 `P` 循环切换，每个模式打日志，用户告诉你哪个对。**

华容道项目最终实测：**需要"上下+左右都翻"**（`{2,1,4,3}`）。
**但这不能照抄** —— 你的游戏/关卡可能不同。**必须实测。**

### 10.4 鼠标：三个必要条件

```
① container.showCursor = true                  ← 否则光标事件完全不来
② 画布上存在「光标检测区域」控件（ClientUICursorEventAreaControl）
   或把监听绑到"有 raycastTarget 的控件"上
③ 在正确的对象上 AddCursorEventListener
```

```lua
-- 显示鼠标（在 ClientUIContainerControl / script.object 上）
pcall(function() script.object.showCursor = true end)

-- 绑定光标事件：绑到 script.object + 所有子控件（覆盖面广，实测有效）
local CE = Enum.CursorEventType
local targets = { script.object }
local ok, kids = pcall(function() return script.object:GetChildren() end)
if ok and kids then
    for _, k in pairs(kids) do targets[#targets+1] = k end
end
for _, c in ipairs(targets) do
    pcall(function()
        c:AddCursorEventListener(CE.CursorClick, function(data)
            local x, y = data:GetUIPos()
            -- 处理
        end)
    end)
end
```

**⚠️ 实测经验**：`script.object` 自身 `raycastTarget` 可能是 `nil`，
所以**只绑它一个是不够的**。绑到"子控件"（尤其那 3 万多个像素控件）反而能收到事件。
**建议一开始就绑到所有子控件**，并把事件打进日志确认。

### 10.5 鼠标滑动（拖拽）

```lua
-- CursorDown 记起点，CursorUp 算位移
local swipe = nil
c:AddCursorEventListener(CE.CursorDown, function(data)
    local x, y = data:GetUIPos(); swipe = { x = x, y = y }
end)
c:AddCursorEventListener(CE.CursorUp, function(data)
    if not swipe then return end
    local x, y = data:GetUIPos()
    local dx, dy = x - swipe.x, y - swipe.y
    swipe = nil
    local min = math.min(W, H) * 0.045     -- 死区，避免误触
    if math.abs(dx) < min and math.abs(dy) < min then return end
    local d
    if math.abs(dx) > math.abs(dy) then d = (dx > 0) and 4 or 3   -- 右/左
    else d = (dy > 0) and 2 or 1 end                              -- 下/上
    -- ★ 这里的 dy>0 判成"下"还是"上"也必须实测确认
    doMove(d)
end)
```

### 10.6 光标刷屏问题

`CursorDrag` 会在拖拽时**每帧触发**。**不要给它打日志**（会把有用信息冲掉）。
只对 `CursorDown` / `CursorUp` / `CursorClick` 打日志。

### 10.7 固定角色 + 屏蔽按键穿透

```lua
pcall(function() script.object.disableKeyEventPassthrough = true end)
-- 之后 WASD 不会让 3D 角色跑动
```

**时机**：进入游戏时打开，退出时恢复（否则玩家一进关卡角色就不能动）。

---

## 11. 生命周期与可重入

| 回调 | 实测时机 |
|---|---|
| `OnInit` | 脚本实例创建 |
| `OnEnable` | 控件被启用（关卡开始时一次） |
| `OnStart` | 紧接着 OnEnable |
| `OnUpdate(dt)` | **需要 `script:EnableUpdate(true)`** |
| `OnDisable` / `OnDestroy` | 控件停用/销毁 |

### 11.1 ★ `script:EnableUpdate(true)` 必须调用

```lua
pcall(function() script:EnableUpdate(true) end)
```

**不调用 → `OnUpdate` 永不触发。** 前人因此连续 4 轮误判成"分帧创建被引擎销毁"。

### 11.2 引擎会销毁重建客户端控件 → 脚本必须可重入

**触发时机**：传送、切换带传送功能的选项卡、容器"隐藏 → 显示"。

重建后 `OnInit → OnEnable → OnStart` 会重跑。所以：

```lua
local built = false
function setupGame()
    -- 1) 清掉上一轮创建的控件（否则无限累积 → 撞上限崩溃）
    if CREATED then
        for _, c in ipairs(CREATED) do
            pcall(game.DestroyClientUIControl, c)
        end
    end
    CREATED = {}
    -- 2) 重建
    ...
end
```

**监听注册要有一次性开关**（否则会重复绑定）。

---

## 12. 完整可复制模板（骨架）

```lua
-- ============================================================
--  2D 小游戏骨架 —— 复制后改 CONFIG 与游戏逻辑即可
-- ============================================================
-- ---------- 一、配置 ----------
local CELL       = 4            -- 每个逻辑像素占多少画布单位
local PW         = 200          -- 像素网格边长（200 是实测上限）
local OVERLAP    = 0.5          -- 每边外扩，消除细缝
local RECT_IMG   = 100001       -- 内置直角白图
local TPL_IMG    = 1073741931   -- ★ 先跑探针确认，或自动探测

-- ---------- 二、状态 ----------
local host, W, H = nil, 0, 0
local CREATED = {}              -- 本脚本创建的全部控件（用于可重入清理）
local flat = {}                 -- flat[(py-1)*PW + px] = 控件
local pixels = nil              -- 解包后的颜色表 {r,g,b}
local swipe = nil

-- ---------- 三、日志 ----------
local function log(...) print("[game] " .. table.concat({...}, " ")) end
local function err(...) printerr("[game] " .. table.concat({...}, " ")) end
local function I(v) return math.floor(tonumber(v) or 0) end

-- ---------- 四、解包（含硬校验）----------
local function unpackTruecolor(hex, expect)
    local raw = (hex:gsub('%x%x', function(cc) return string.char(tonumber(cc,16)) end))
    local out, n, i, len = {}, 0, 1, #raw
    while i + 3 <= len do
        local r,g,b,run = string.byte(raw,i), string.byte(raw,i+1),
                          string.byte(raw,i+2), string.byte(raw,i+3)
        for _ = 1, run do n = n + 1; out[n] = {r,g,b} end
        i = i + 4
    end
    if expect and n ~= expect then
        err(string.format("解包 %d != 期望 %d", n, expect))
    end
    return out
end

-- ---------- 五、建控件 ----------
local function newBlock(color, size)
    local ctl = game.InstantiateClientUIControl(TPL_IMG, host)
    if ctl == nil then return nil end
    pcall(function() ctl:SetAnchorMin(0.5,0.5) end)
    pcall(function() ctl:SetAnchorMax(0.5,0.5) end)
    pcall(function() ctl:SetPivot(0.5,0.5) end)
    pcall(function() ctl:SetSizeDelta(size + OVERLAP*2, size + OVERLAP*2) end)
    pcall(function()
        ctl.SetImage(ctl, Enum.ImageSource.StaticReference, RECT_IMG)
        ctl.imageType = Enum.ImageType.Stretch
        if color then
            ctl.imageColor = Color.FromRGBA(color[1], color[2], color[3], 255)
        end
    end)
    CREATED[#CREATED+1] = ctl
    return ctl
end

-- ---------- 六、建整幅图（★ 一次画到位，不二次改色）----------
local function buildBoard()
    local half = (PW - 1) * 0.5
    local BOARD_X, BOARD_Y = 0, 0
    local t0 = os.clock()
    for py = 1, PW do
        for px = 1, PW do
            local ctl = newBlock(pixels[(py-1)*PW + px], CELL)
            if ctl then
                ctl:SetAnchoredPosition(BOARD_X + (px-1-half)*CELL,
                                        BOARD_Y + (half-(py-1))*CELL)
                flat[(py-1)*PW + px] = ctl
            end
        end
        if py % 50 == 0 then
            log(string.format("  %d/%d 行（%d 控件，%.1f s）", I(py), PW, #CREATED, os.clock()-t0))
        end
    end
    log(string.format("构建完成：%d 控件，%.1f s", #CREATED, os.clock()-t0))
end

-- ---------- 七、生命周期 ----------
function OnStart()
    log("===== 启动 =====")
    host = script.object
    -- ★ 强制可重入
    if #CREATED > 0 then
        for i = 1, #CREATED do pcall(game.DestroyClientUIControl, CREATED[i]) end
        CREATED = {}
    end

    -- ★ 显示鼠标 + 固定角色
    pcall(function() host.showCursor = true end)
    local _, vcur = pcall(function() return host.showCursor end)
    log("showCursor = " .. tostring(vcur))
    pcall(function() host.disableKeyEventPassthrough = true end)

    -- ★ 探测模板（若 TPL_IMG 失效）
    -- local t, cls = discoverTemplate("ClientUIImageControl")
    -- if t then TPL_IMG = t; log("模板 -> " .. t .. " (" .. cls .. ")") end

    W, H = game.GetUICanvasSize()
    W, H = I(W), I(H)
    log(string.format("画布 %d×%d  CELL=%d  %d×%d 像素", W, H, CELL, PW, PW))

    pixels = unpackTruecolor(PIXEL.RGB, PW * PW)
    if #pixels ~= PW * PW then
        err(string.format("!! 数据长度 %d != %d，终止", #pixels, PW*PW))
        return
    end

    buildBoard()
    bindInput()
    pcall(function() script:EnableUpdate(true) end)
    log("===== 可以开始玩了 =====")
end

function OnUpdate(dt)
    -- 需要持续逻辑时写这里
end

function OnDestroy()
    if host then
        pcall(function() host:RemoveAllKeyEventListeners() end)
        pcall(function() host:RemoveAllCursorEventListeners() end)
    end
end
```

---

## 13. 排错手册（症状 → 根因 → 修法）

| 症状 | 根因 | 修法 |
|---|---|---|
| **屏幕一片白** | 数据表为空，`if color then` 静默跳过 → 控件保持默认白 | 解包后**硬校验长度** |
| **块内横条（只有 Y 错）** | 取色索引用 `K` 作行步长，而行宽是 `PW` | 用 `(gy*K+by)*PW + (gx*K+bx)` |
| **整幅错位一格** | `HOLE_TAG` 是数字不是 nil，`if d then` 把它当有效块 | `if d and d ~= HOLE_TAG then` |
| **移动后源格残留** | 只重画了目标格 | 两格都重画 |
| **打乱后颜色错乱** | 取色用了"目标格"位置 | 用"块自身"位置 |
| **先建后重绘 → 条纹** | 同一控件被二次改色 | **一次画到位** |
| **`OnUpdate` 从不触发** | 漏 `script:EnableUpdate(true)` | 补上 |
| **实例化全返回 nil** | ① 模板不是"存为模板"的控件 ② 宿主是画布根本身 | 存为模板 + 宿主用**画布根的子控件** |
| **扫到非图片模板** | 只判断"能实例化"，没验类名 | 用 `tostring(ctl)` 验 `ClientUIImageControl` |
| **脚本无限重建/卡死** | 控件数超上限（> 52,000） | 降分辨率；止血 = `tools\kill.bat` |
| **`attempt to index a nil value (global 'x')`** | 局部变量作用域（`local` 声明在别处） | 提升为模块级变量 / 前置声明 |
| **移动完全无反应** | 处理函数内抛错 | **看报错日志的行号**（会精确指到行） |
| **点击命中格上下镜像** | `GetUIPos()` 以左下角为原点 | `x - W/2, H/2 - y` |
| **鼠标光标不出现 / 事件不来** | 没设 `showCursor`；或只绑了容器（`raycastTarget=nil`） | 设 `showCursor=true` + **绑到子控件** |
| **拖拽时日志刷屏** | 给 `CursorDrag` 打了日志 | 只记 `Down/Up/Click` |
| **WASD 让角色乱跑** | 没开 `disableKeyEventPassthrough` | 容器上设 `true` |
| **方向反了** | 键位↔方向映射反 | **做成可切换 + 让用户实测选定** |
| **退出后界面自己冒出来** | 容器只开没关 | 退出时服务端 `[384] 显示状态=关闭` |
| **改完脚本没生效** | 忘了"退出关卡 → 重新进入" | 提醒用户；或用 `deploy.bat` 校验哈希 |

---

## 14. 离线模拟器（强烈建议）

用 **fengari** 在 Node 里跑 Lua，把逻辑（移动/判定/解算）先验证掉再上游戏：

```javascript
const { lua, lauxlib, lualib, to_luastring, to_jsstring } =
    require('<path>/node_modules/fengari');
const L = lauxlib.luaL_newstate(); lualib.luaL_openlibs(L);
lauxlib.luaL_dofile(L, to_luastring('sim.lua'));
```

**mock 需要覆盖**：

```lua
game.GetUICanvasSize()            → 1599, 899.5
game.InstantiateClientUIControl() → 假控件（可控制返回 nil 模拟失败）
game.DestroyClientUIControl()
game.GetCursorUIPos()
Enum.ImageSource / ImageType / CursorEventType / KeyEventType
Color.FromRGBA()
script.object / script:EnableUpdate()
print / printerr
```

**⚠️ 必须「内联加载」脚本内容，不能用 `loadfile()`**：
`loadfile` 会把脚本当成独立 chunk，脚本里的 `local PIXEL/THUMB` 对调用方不可见
→ **模拟结果全错**（前人因此误判过两轮）。

**正确做法**：

```python
# 生成一个"内联版"用于模拟
env = open('sim_env.lua').read()       # 假引擎
body = open('game_full.lua').read()    # 真实脚本（含内联数据）
tail = open('sim_tail.lua').read()     # 断言
open('sim_inline.lua','w').write(env + body + tail)
```

---

## 15. 工具链

### 15.1 本 skill 自带

| 工具 | 用途 |
|---|---|
| `tools\deploy.bat` | 一键部署脚本到关卡（自动找路径 + 备份 + 校验哈希） |
| `tools\kill.bat` | 紧急止血：把脚本换成空脚本 |
| `templates\2D-ready.gil` | 含全部必需模板的 2D 关卡模板 |

### 15.2 配套的外部工具（`E:\DSHworker\tools\`）

| 工具 | 用途 |
|---|---|
| `ugc-json.js` | `.gil/.gia ⇔ JSON` 无损互转 |
| `probe-gil.js` | `<file> --ui` 列控件组 / `--path` / `--find` / `--findstr` |
| `patch-script.js` | 替换 `.gil` 里的 Lua 源码（一般不需要） |
| `extract-lua.js` | 抽出 `.gil` 里当前真正在跑的 Lua |
| `ugc-diff.js` | 两个 `.gil` 差分 |
| `kb.js` | 取官方文档（`list` / `get "标题"`） |
| `beyond-node-search.js` | 搜服务端节点（876 个） |

### 15.3 静态检查（`luacheck.js`）

fengari 驱动的 Lua 5.3 检查，四项：
1. 语法 + 生命周期回调清单
2. **大写常量：用了但没声明**（会静默 nil）
3. **前置声明检查**：调用了后面才声明的局部函数
4. 官方 API 名拼写抽查

**⚠️ 它查不出"局部变量在别处声明"** —— 那个只能靠 `printerr` 打印堆栈。

---

## 16. 服务端联动（仅 n 需要"选项卡进入/退出"时）

如果你要做的是"点选项卡进入小游戏、点退出按钮收起"，需要服务端节点图：

```
【A. 进入】[307] 选项卡选中时 → [是否相等(序号)] → [384] 设置界面控件(组)状态(显示)
                                                   → [300005] 发送客户端脚本信号
【B. 退出】[300001] 监听信号 → [248] 获取在场玩家实体列表 → [128] 取列表第 0 项
                             → [384] 设置界面控件(组)状态(关闭)   ← ★ 必须有！
```

**⚠️ A 和 B 必须成对** —— 只做 A 不做 B 会导致：
容器永久停在"显示"状态 → 之后**任何一次引擎重建**（传送/切选项卡）都会让小游戏自己冒出来。
同时会造成"退出后鼠标光标残留"。

客户端侧：

```lua
script:RegisterServerSignalHandler("GameReset", function()
    setupGame()      -- 重开一局
end)

-- 退出时发信号
local sig = game.ServerSignal("GameExit")
sig:SendSignal()
```

**⚠️ 信号可能在"控件刚重建"的瞬间丢失**（新实例还没注册监听）。
→ 关键流程要有 `OnStart` 兜底。

---

## 17. 与用户协作的要点

### 17.1 编辑器操作必须给"逐级点选路径"

用户**只能手工操作**，所以要给到能直接照抄的程度：

```
界面控件组管理 → 界面布局 → 布局详情/自定义 → 点「客户端控件容器」
  → 右侧「画布设置」→【前往编辑】
  → 左下角【添加控件】→ 选「图片」
  → 选中它 → 点底部【存为模板】    ← ★ 别漏这步
```

### 17.2 每个实验前先说清"预期看到什么"

> ❌ "再跑一次看看"
> ✅ "这次日志里应该出现 `showCursor -> true`，屏幕上应该出现鼠标光标。如果日志是 `false`，告诉我。"

### 17.3 用户说"不行"时，先要日志

不要猜。**日志里有行号，能直接定位。**

### 17.4 用户的主观描述是一等证据

实战中用户这三句话都**直接指对了方向**：
- "参考图正常，不太可能是编辑器问题" → 排除了整条错误路径
- "仅 y 上出现错误" → 直接定位到索引步长 bug
- "明显是循环出问题" → 促成了循环重写

**不要忽略用户的直觉判断，它往往基于他们看到的画面。**

### 17.5 破坏性操作先备份

`.gil` 尤其。一条命令：

```powershell
Copy-Item $gil "$gil.bak_$(Get-Date -Format yyyyMMdd-HHmmss)"
```

---

## 18. 复盘：前人走的弯路（**别重犯**）

| 弯路 | 根因 | 本可以 |
|---|---|---|
| 反复往 `.gil` 里塞脚本/控件 | 不知道 `external_lua_file` 是权威 | **第一步就该找"编辑器从哪读脚本"** |
| 花 8+ 轮试 `InstantiateClientUIControl` | 没读懂"仅存为模板的控件可被动态创建" | 一次性把"存为模板"试掉 |
| 得出"此 API 不可用"的错误结论 | 宿主给了画布根本身 | 宿主必须是**画布根的子控件** |
| 4 轮误判"分帧创建被引擎销毁" | 漏 `script:EnableUpdate(true)` | 第一轮就写探针测 OnUpdate |
| 3 轮怀疑 `SetAsLastSibling` / `pcall` 开销 | 没先做逐档 API 计时 | 先跑性能探针（每档 1024 个） |
| **5+ 轮调分辨率 / ε / 块分组** | 真凶是**数据索引约定**（`K` vs `PW`） | **生成器 + 渲染器共享同一索引公式并各自自检** |
| 2 轮"屏幕一片白" | 空数据被 `if color then` 静默吞掉 | 解包后**硬校验长度** |
| 2 轮"整幅错位" | `HOLE_TAG` 数字被当有效块 | 空洞判据用 `d ~= HOLE_TAG` |
| 1 轮"移动无反应" | 处理函数抛错 | 动作全套 `pcall` + `printerr` 堆栈 |
| 1 轮"源格残留" | 只重画目标格 | 移动即重画两格 |
| 2 轮"参考图消失" | 绘制循环被改成 `if false then` 没恢复 | 每次改动后**核对"应存在的绘制段数量"** |
| 多次误判控件上限 | 把"移动报错"误读成"脚本被销毁" | **看报错堆栈**，它会明确指到行号 |
| "点了没反应"查了两轮 | 漏前置声明 → 全局 nil | 用 `luacheck.js` 静态检查 |
| "蛇跑几步就坏" | `destroySeg` 里先置 nil 再 `table.remove` | 数组改动只在一处做 |
| "计数器没了"→"棋盘盖住蛇" | `SetSiblingIndex` 是**插入**语义 | 递增游标一次定序 |
| 光标残留 | 全局副作用放在了去重检查之前 | 副作用一律放最后 |

**最大的单点经验**：

> **先把"数据约定"和"渲染约定"写在同一份文档里，并让生成器和渲染器各自自检。**
> 前人花在"索引约定不一致"上的往返，超过了其余所有问题的总和。

---

## 19. 关键数字速查

```
【画布与坐标】
画布尺寸（本机）           1599 × 899 画布单位
画布→物理缩放 s            ≈ 1.07 ~ 1.14（非整数 → 摩尔纹上限）
每逻辑像素建议物理点数       ≥ 6

【性能（实测）】
控件创建（一次性爆发）       0.256 ~ 0.41 ms/个
控件创建（分帧）             > 5 ms/个（慢 20 倍，禁止使用）
单控件改色                  0.004 ~ 0.007 ms
全盘重画 16,384 次改色       0.09 ~ 0.11 s
耗时公式                   秒 = 控件数 × 0.000256 × 1.5

【上限（实测）】
稳定                        51,664 控件（200×200 + 108×108）
崩溃                        61,440 控件（建成即崩，无限重建）
安全线                      < 52,000

【已验证配置】
最高可用                    200×200 + 108×108 = 51,664 控件，构建 2.7 s，脚本 422 KB
推荐                        160×160 + 108×108 = 37,264 控件，构建 2.0 s，脚本 312 KB
轻量                        128×128 + 108×108 = 28,048 控件，构建 ~7 s

【其它】
真彩颜色数（实测）           12,993 色（96 色调色板 = +135 倍）
迭代一轮                    ≈ 20 秒
数据量（真彩 RLE）          160² ≈ 95 KB；200² ≈ 146 KB；108² 参考图 ≈ 44 KB
```

---

## 20. 交付检查清单

在告诉用户"做完了"之前，确认：

- [ ] **脚本能跑通**：日志有 `构建完成：N 控件`，屏幕能看到画面
- [ ] **数据有硬校验**：解包长度不符时 `err` 并 `return`
- [ ] **生成器有自检**：块内单色断言通过
- [ ] **控件数 < 52,000**
- [ ] **`script:EnableUpdate(true)` 已调用**（若用到 OnUpdate）
- [ ] **脚本可重入**：`OnStart` 里先清理上一轮的控件
- [ ] **输入已实测**：方向、鼠标点击、拖拽都验证过
- [ ] **`showCursor` 和 `disableKeyEventPassthrough` 已设**
- [ ] **移动后重画两格**（若是有移动的游戏）
- [ ] **不变量校验**（每次移动后查，能立刻发现逻辑 bug）
- [ ] **给了用户玩法说明**（操作键位、目标、重开方式）
- [ ] **把本次实测数字写回本文件**（让下一个 Agent 受益）

---

## 21. 命令行工具踩坑（**构建本 skill 时新踩到的**）

这一节记录的是"写工具脚本"时的坑，不是游戏逻辑的坑。

### 21.1 `.bat` 必须**纯 ASCII**

**症状**：`deploy.bat` 里写了中文提示，运行时报

```
'cho' is not recognized as an internal or external command
```

注意报的是 **`cho`** 而不是 `echo` —— 说明 cmd 解析首行时丢了一个字节。

**根因**：Windows `cmd.exe` 按 **ANSI**（中文系统是 GBK）解析 `.bat` 文件。
如果 `.bat` 是**无 BOM 的 UTF-8** 且含中文，多字节序列会被解析错乱，
甚至让 `echo` 的首字节被吃掉。

**加 UTF-8 BOM 不可靠**：实测加 BOM 后 cmd 仍可能报错。

**唯一可靠做法：`.bat` 只用 ASCII 字符。**
中文说明放到 `README.md` 里，命令行输出也用英文。

```bat
rem  ✅ 正确：纯 ASCII
echo [ERROR] File not found: %SRC%

rem  ❌ 错误：含中文（即使加了 BOM 也可能被截断）
echo [错误] 找不到文件: %SRC%
```

**验证方法**（PowerShell）：

```powershell
$bytes = [System.IO.File]::ReadAllBytes('deploy.bat')
$nonAscii = ($bytes | Where-Object { $_ -gt 127 }).Count
Write-Host "非 ASCII 字节数 = $nonAscii"      # 必须为 0
```

### 21.2 `if exist` 里的通配符展开**不可靠**

```bat
rem ❌ 不可靠：路径里带 *，if exist 不一定能正确展开
if exist "%%D\BeyondLocal\*\Beyond_Local_Save_Level\%LEVEL%\external_lua_file" (
    set "DST=%%D\BeyondLocal"
)

rem ✅ 可靠：显式逐层 for /d 遍历
set "DST="
for /d %%G in ("%MIHOYO%\*") do (
    if not "!DST!"=="" goto :found
    if exist "%%G\BeyondLocal" (
        for /d %%U in ("%%G\BeyondLocal\*") do (
            if not "!DST!"=="" goto :found
            if exist "%%U\Beyond_Local_Save_Level\%LEVEL%\external_lua_file" (
                set "DST=%%U\Beyond_Local_Save_Level\%LEVEL%\external_lua_file"
            )
        )
    )
)
:found
```

**顺带一个发现**：`AppData\LocalLow\miHoYo\` 下**可能有多个游戏目录**
（如 `原神` 与 `Genshin Impact` 各有一份 `BeyondLocal`）。
所以**不要"取第一个目录"，要"按关卡 ID 匹配"** —— 哪个目录下真的存在这个关卡就用哪个。

### 21.3 ★ 测试部署脚本前，**先备份真实脚本**

我在测试 `deploy.bat` 时，用一个 47 字节的测试文件把用户**正在运行的
317 KB 游戏脚本**覆盖掉了。虽然从本地源文件恢复了，但这个错误完全可以避免。

**正确做法**：

```powershell
# 1) 先备份
Copy-Item $dst "$dst.test_backup"
# 2) 用一个"不会被误用的关卡 ID"测试路径探测逻辑
cmd /c "deploy.bat test.lua 9999999999"      # 不存在的关卡 → 只测路径逻辑
# 3) 确认逻辑正确后，才用真实关卡 ID 测完整流程
```

**或者更好**：给工具加 `--dry-run` 模式，只打印将要做什么，不实际写文件。

### 21.4 PowerShell 传中文给 `cmd /c` 会乱码

```powershell
# ❌ 中文参数经 PowerShell → cmd 时编码转换，可能乱码
cmd /c "deploy.bat 中文路径.lua"

# ✅ 用变量传递，或用 8.3 短路径，或干脆避免中文参数
$src = '...'; cmd /c "deploy.bat `"$src`" 1073741837"
```

### 21.5 教训总结

| 坑 | 一句话教训 |
|---|---|
| `.bat` 含中文 | **`.bat` 只用 ASCII**，加 BOM 也不可靠 |
| `if exist` 通配 | **显式逐层 `for /d` 遍历** |
| 测试覆盖真实文件 | **测试前先备份，或先跑 dry-run** |
| 多游戏目录 | **按关卡 ID 匹配**，不要取"第一个目录" |

> **通用原则**：写"会修改用户数据的工具"时，**先让它能在不写任何文件的情况下跑通**，
> 再加写入逻辑。这次如果先做个 `--dry-run`，就不会覆盖用户的脚本了。

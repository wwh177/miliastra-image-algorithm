# ★★★ AGENT_GUIDE.md —— 面向 AI Agent 的完整使用说明 ★★★

> **这份文档是给"另一个 AI agent"看的。**
> 目标：让你**不需要读源码**就能正确调用这套工具，并且**不踩已知的坑**。
>
> 如果你只有 60 秒：直接跳到 [§1 最快路径](#1-最快路径60-秒上手)，跑两条命令即可。
> 如果你要做任何"改参数/换图/换分辨率"的事：**必须先读 [§4 硬限制](#4-硬限制必须遵守)**。

---

## 目录

1. [最快路径（60 秒上手）](#1-最快路径60-秒上手)
2. [文件清单与职责](#2-文件清单与职责)
3. [能力总览（这套工具能做什么）](#3-能力总览这套工具能做什么)
4. [硬限制（必须遵守）](#4-硬限制必须遵守)
5. [输入参数总表](#5-输入参数总表)
6. [输出格式规范（精确到字节）](#6-输出格式规范精确到字节)
7. [命令行接口（CLI）](#7-命令行接口cli)
8. [Python API（可直接 import）](#8-python-api可直接-import)
9. [Lua 端接口（render.lua / render_modes.lua）](#9-lua-端接口renderlua--render_modeslua)
10. [常见任务配方（Recipes）](#10-常见任务配方recipes)
11. [故障排查表](#11-故障排查表)
12. [自检命令（改代码后必跑）](#12-自检命令改代码后必跑)
13. [已实测数据（用于决策）](#13-已实测数据用于决策)

---

## 1. 最快路径（60 秒上手）

```bash
pip install pillow numpy

# ① 压缩：把图变成"块数据"lua 文件
python compress.py --input 你的图.png --output out.lua --std 3 --size 300x300

# ② 把 out.lua 的内容整段粘进 render.lua 的『数据区』
#    数据区标记：从 `local IMG = {}` 到 `-- ▲▲▲ 数据区结束 ▲▲▲` 之前

# ③ 把 render.lua 部署到关卡（见 §9.2），进关卡即可看到图
```

**不确定参数？先估算**（不改动任何文件）：

```bash
python estimate.py --input 你的图.png --size 300x300 --scan-std 0,1,2,3,4,6,8,12
```

输出一张表：每档的**块数（=控件数）**、**MAE（色差）**、预估建立耗时、是否超限。挑一行即可。

---

## 2. 文件清单与职责

| 文件 | 类型 | 职责 | 何时用 |
|---|---|---|---|
| `AGENT_GUIDE.md` | 文档 | **本文档**（agent 首选） | 任何时候 |
| `README.md` | 文档 | 人类可读的完整说明 | 需要背景知识时 |
| `blockcodec.py` | 库 | 块列表编解码（hex / b64）、扫描推演、MAE | 被下面两个脚本 import |
| `compress.py` | 工具 | 单图压缩 → 1 个 lua 数据文件 | **主流程** |
| `render.lua` | Lua | 千星奇域渲染器（读 compress.py 输出） | **主流程** |
| `pack_modes.py` | 工具 | 同图多档（多组 STD/分辨率）打包成 1 个文件 | 调参对比时 |
| `render_modes.lua` | Lua | 多档渲染器（按 P 键切档对比） | 与 pack_modes 配套 |
| `assemble_modes.py` | 工具 | 把数据自动拼进 render_modes.lua | 与上面两个配套 |
| `estimate.py` | 工具 | 只估算块数 + MAE，不写文件 | **选参数时** |
| `verify_toolkit.py` | 测试 | 端到端验证（含"用 render.lua 的解码器解压"） | 改代码后 |
| `verify_modes2.py` | 测试 | 多档链路验证 | 改代码后 |
| `selftest.py` | 测试 | 基础自测（几何不变式等） | 改代码后 |
| `check_lua.js` | 测试 | 用 fengari 验证 Lua 语法 | 改代码后 |

---

## 3. 能力总览（这套工具能做什么）

| 能力 | 入口 | 说明 |
|---|---|---|
| 图片 → 可控数量的纯色矩形 | `compress.py` | 用 STD 换控件数（0=无损，越大越省但越糊） |
| 估算控件数与画质 | `estimate.py` | 不写文件，秒级给出"块数 + MAE + 耗时" |
| 任意分辨率输出 | `compress.py --size WxH` | 允许变形；`--lock-aspect` 可锁定比例 |
| 真彩不量化 | `--bits 8`（默认） | 24 位真彩，不做调色板 |
| 块数据紧凑编码 | `--enc b64`（默认）/ `hex` | b64 比 hex 再省 30%（已实测通过） |
| 多档并存 + 游戏内按键切换 | `pack_modes.py` + `render_modes.lua` | 同屏同尺寸对比不同参数 |
| MAE（画质）报告 | `compress.py` / `estimate.py` | 每像素每通道平均绝对色差 |
| 几何/编码自检 | `compress.py` 自动 | 空洞/重叠/越界/坐标推演，全为 0 才算通过 |

**这套工具**不做**的事**：不做有损通用压缩（JPEG 类）；不生成 PNG 以外的图片格式；
不直接修改关卡 `.gil`（只产出外部 `.lua`）。

---

## 4. 硬限制（必须遵守）

### 4.1 单次回调时长上限（**不是控件数上限**）★ 2026-10 修订

**旧结论（已推翻）**：以前认为"控件数 > 5 万就崩溃"。

**实际情况**：**没有控件数硬上限**。真正的限制是【**单次回调约 22 秒**】：

```
★ 决策阈值：【50,000 个控件】
   ≤ 50,000  →  ★ 推荐 OnStart 单次回调建立 ✓✓（更快更简单）
   >  50,000  →  必须分帧创建 ✓（见 §4.1.1 与 大批量控件-分帧创建.md）

   实测依据（20,000 个）：OnStart 单次 8.06 s  vs  分帧隐藏 10.78 s
   → 少控件时单次回调反而【快 34%】✓✓
```

| 控件数 | OnStart 单次回调 | 分帧创建 |
|---|---|---|
| 37,264 | ✓ 稳定（约 11 s） | ✓ |
| **50,000** | ✓ 正常（约 22 s，**推荐上限**） | ✓ |
| 61,440 | ❌ 引擎中断/销毁脚本（表现为卡死） | ✓ |
| 90,000 ~ 100,000 | ❌ | ✓ **实测稳定** |
| 167,915 | ❌ | ✓ 能建成（约 2~3 分钟） |

```
超时的表现：日志 "Lua execution took too long"，然后【静默中断】脚本
  —— 最隐蔽的是"数据只处理了一部分"：
     一次解析 167,915 块被截断在 132,000 块（画面缺一条，无任何报错）

另一个独立限制：每帧渲染 ≈ 15~18 µs × 可见控件数（"能不能玩"的天花板）
  5,000 可见 → 81 ms(12 fps)   20,000 可见 → 301 ms(3 fps)
```

**块数超限时的正确做法（按优先级）**：
1. ★ **开启动态 STD**（默认已开启）→ 块数直接 **−30~34%**，画质不变
2. **提高 STD** 或 **降低分辨率**（后者同时省控件且观感更干净）
3. ★ **改用分帧创建**（每帧 40 ms，全过程不卡死）→ 可上到 **10 万控件以上**
   完整方法见 `2D项目-skill/examples/大批量控件-分帧创建.md`

`compress.py --max-blocks`（默认 45,000）会在超过时告警。

> **注意区分两件事**（容易混淆）：
> - **创建方式**：≤50,000 用 OnStart 单次 ✓；>50,000 用分帧 ✓
> - **隐藏/显示方式**：**无论多少都建议**"隐藏组下建立 → 建完分帧显示" ✓
>   （为的是运行帧率提升约 9 倍：20,000 个可见 301 ms/帧 → 隐藏再显示 35 ms/帧 ✓✓）

### 4.2 每个块的 w/h 必须 ≤ 255

编码用单字节存 w,h，**单块 w/h 必须 ≤ 255**。

V1.1 起三层防护：
1. `compress.py` / `estimate.py` 在**生长阶段**就把 w/h 限制在 255 以内（`CONFIG["MAX_DIM"]`，默认 255）；
2. `blockcodec.py` 的 `pack_hex` / `pack_b64` 遇到 >255 会 **抛 `ValueError`**（不再静默 `&255`）；
3. `compress.py` 的第三项自检「块尺寸」会核对并参与退出码。

> ⚠️ **触发条件不是 STD，而是「图里有没有跨度 >255px 的大块均匀区域」。**
> 素材换成平涂/几何/纯色底（含 `--lock-aspect` 的白边）就会命中，
> 而这些恰好是 README 推荐的第 1 类素材。V1.0 在这里是**静默画错整张图**（实测覆盖率掉到 0~14.7%）。

### 4.3 不要用 Lua 表存大量块

**实测**：
- 62,000 个表构造器 / 1.23 MB 脚本 → 引擎**正常加载**
- 89,000 个表构造器 / 2.01 MB 脚本 → 引擎**完全无日志**（编译期就失败）

所以块数据必须用**字符串编码**（本工具默认如此）。**不要**改成 `{{x,y,w,h,c},...}`。

### 4.4 输出 lua **不能带 `return`**（除非当独立模块用）

`compress.py` 的输出要**整段粘进 render.lua 的数据区**，而 Lua 规定
`return` 必须是块的最后一条语句。粘在中间会报
`'<eof>' expected near 'local'`，表现为**进关卡后无日志、无画面**。

- 默认：不含 `return`（正确，用于粘贴）
- 当独立模块用（`require`/`dofile`）才加 `--with-return`

### 4.5 不能假设 Lua 是 64 位整数

实测（fengari 模拟器复现）：`807136431 * 64 + 24` 得到 `117124056`
（正确应为 `51656731608`，即发生了 **32 位回绕**）。

因此本工具的编码/解码**每一步运算都 < 2^24**：
- base64 拆成"24 位 + 16 位"两组（不是 40 位大整数）
- 校验和用 2^24 模（不是 2^32）

**如果你要改编解码，必须保持这个约束。**

### 4.6 关卡必须存在"已存为客户端控件模板"的图片控件

`render.lua` 靠克隆这个模板来建控件。做法见 [§9.2](#92-部署到千星奇域)。
没有它，渲染器会打印 `找不到可用的图片控件模板` 并停止。

### 4.7 脚本部署位置与迭代方式

```
<存档目录>/Beyond_Local_Save_Level/<关卡ID>/external_lua_file/<脚本名>.lua
```

- 编辑器**不会**把脚本写进 `.gil`；`.gil` 每次进关卡都被编辑器重写
- 所以**只需维护外部 `.lua`**，改完直接覆盖即可，**不需要重启编辑器**（迭代约 20 秒）
- `<脚本名>` 必须与关卡里挂载的脚本名一致

---

## 5. 输入参数总表

### 5.1 `compress.py`

| 参数 | CLI | 类型 | 默认 | 取值范围 | 说明 |
|---|---|---|---|---|---|
| 输入图片 | `--input` | path | `input.png` | 任何 Pillow 支持的格式 | png/jpg/webp/bmp… |
| 输出文件 | `--output` | path | `output.lua` | — | 目录会自动创建 |
| **容差** | `--std` | float | `3` | **0 ~ 1024 任意值** | 0=无损；越大块越少越糊。**最重要参数** |
| 输出分辨率 | `--size` | `WxH` | `300x300` | 正整数 | 比例不同会被拉伸（除非锁比例） |
| 锁定长宽比 | `--lock-aspect` | flag | 关 | — | 保持比例缩放后居中放入框内（空白填白） |
| 允许变形 | `--no-lock-aspect` | flag | 开 | — | 直接拉伸到 `WxH` |
| 颜色位数 | `--bits` | int | `8` | 1~8 | 8=24 位真彩、不量化（**推荐**） |
| **块数据编码** | `--enc` | `b64`\|`hex` | `b64` | — | b64 比 hex 省 30%；hex 可肉眼查看 |
| 输出预览图 | `--preview` | flag | 关 | — | 额外输出 `*_preview.png` |
| 块数告警阈值 | `--max-blocks` | int | `45000` | — | 超过只告警不阻断 |
| **动态 STD** | `--dyn-std` / `--no-dyn-std` | flag | **开** | — | **默认开**（块数 −30~34%）；关掉可退回全局 STD |
| 动态·细节容差 | `--t1-std` | float | `=STD` | 正数 | 覆盖自动值 |
| 动态·过渡容差 | `--t2-std` | float | `=2×STD` | 正数 | 覆盖自动值 |
| 动态·平坦容差 | `--flat-std` | float | `=3×STD` | 正数 | 覆盖自动值 |
| 动态·三个阈值 | `--t1` `--t2` `--flat` | float | `30 12 =t2` | 正数 | **不懂别改** |
| 动态·倍数/半径 | `--dyn-m2` `--dyn-m3` `--dyn-r` | float/int | `2 3 2` | — | 自动推导时用 |
| Lua 变量名 | `--var-name` | str | `IMG` | 合法标识符 | 同时改 render.lua 里的引用名 |
| 加 return | `--with-return` | flag | 关 | — | **仅当输出当独立模块用时加**（见 §4.4） |
| JSON 配置 | `--config` | path | — | — | 覆盖 CONFIG 区（优先级：CLI > JSON > CONFIG） |

### 5.2 `estimate.py`

| 参数 | CLI | 说明 |
|---|---|---|
| 输入图片 | `--input` | 同上 |
| 分辨率 | `--size WxH` | 单次估算 |
| 容差 | `--std` | 单个 STD |
| **扫描 STD** | `--scan-std 0,1,2,3,4,6,8` | 一次算多个，逗号分隔（**选参数推荐用法**） |
| **扫描分辨率** | `--scan-size 200,300,400` | 一次算多个正方形边长 |
| 锁比例 | `--lock-aspect` | 同上 |
| 颜色位数 | `--bits` | 默认 8 |
| 安全上限 | `--safe-limit` | 影响"判定"列，默认 45000（单次回调安全值） |
| **动态 STD** | `--dyn-std` / `--no-dyn-std` | 默认开；关掉可与全局 STD 对比 |
| **六个动态参数** | `--t1-std` `--t2-std` `--flat-std` `--t1` `--t2` `--flat` | 覆盖自动值 |
| 分帧预算 | `--frame-budget 40` | 预估"分帧创建"需要多少帧 |
| 几何自检 | `--geometry-check` | 顺带检查空洞/重叠/越界/扫描顺序 |
| 输出预览图 | `--preview` | 每档输出 `estimate_preview_WxH_stdN.png` |
| JSON 配置 | `--config` | 同上 |

### 5.3 `pack_modes.py`（多档）

| 参数 | CLI | 说明 |
|---|---|---|
| 输入图片 | `--input` | — |
| **每档规格** | `--specs 256:1,200:0` | `分辨率:STD` 列表（**推荐**） |
| 或统一分辨率 | `--size 256 --stds 1,2,3` | 旧写法，等价于 `--specs 256:1,256:2,256:3` |
| 颜色位数 | `--bits` | 默认 8 |
| 编码 | `--enc b64\|hex` | 默认 b64 |
| 输出 | `--out` | — |
| 预览图 | `--preview` | 每档一张 |
| 锁比例 | `--lock-aspect` | — |

### 5.4 `assemble_modes.py`

```
python assemble_modes.py <数据文件.lua> <render_modes.lua> <输出.lua>
```

按标记替换数据区（起始 `local MD = {}`，结束 `-- ▲▲▲ 数据区结束 ▲▲▲`）。

---

## 6. 输出格式规范（精确到字节）

### 6.1 `compress.py` 输出（单图）

```lua
-- 由 compress.py 生成（最大对齐矩形合并压缩）
-- STD=3.0  COLOR_BITS=8  分辨率=300x300  编码=b64  块数=30612  MAE=1.17
-- 用法：把本文件【全部内容】替换进 render.lua 的『数据区』
local IMG = {}
IMG.N = 300
IMG.W = 300
IMG.H = 300
IMG.STD = 3.0
IMG.ENC = "b64"
IMG.NBLK = 30612
IMG.MAE = 1.17
IMG.DATA = "<块数据>"
```

| 字段 | 类型 | 含义 |
|---|---|---|
| `N` | int | 边长（源像素，正方形） |
| `W`/`H` | int | 逻辑宽高（当前等于 N） |
| `STD` | number | 使用的容差 |
| `ENC` | string | `"b64"` 或 `"hex"` |
| `NBLK` | int | 块数 = **需要的控件数** |
| `MAE` | number | 矩形合并的平均绝对色差（0~255/通道） |
| `DATA` | string | 编码后的块数据 |

### 6.2 块数据位布局（**坐标不存储**）

块按 **行主序扫描顺序** 排列。第 i 块的 `x,y` 由解码端**重放扫描**还原：

```
维护 occupied[col] = 该列已被占用到的最大行号（初始 -1）
游标 (ci,cj) 从 (0,0) 起：
  跳过 occupied[ci] >= cj 的列；ci 越界则 cj+=1, ci=0 继续跳
  得到 (x,y) = (ci,cj)
放块 (w,h) 后：occupied[ci..ci+w-1] = max(该值, cj+h-1) ； ci += w
```
> 该性质已由 `compress.py` 自动自检（`check_scan_order`，必须为 0 处不一致）。

**hex 编码**（10 字符/块）：
```
每个块 10 个 hex 字符 = w(2) h(2) r(2) g(2) b(2)     ← 各 1 字节
```

**b64 编码**（7 字符/块）：
```
组1（4 字符）：w,h,r 三个字节 → 24 位 → 4×6 位
     a = ((c1*64+c2)*64+c3)*64+c4        < 2^24
     w = a // 65536 ; h = (a // 256) % 256 ; r = a % 256
组2（3 字符）：g,b 两个字节 → 16 位 → 3×6 位
     b2 = (c5*64+c6)*64+c7               < 2^18
     g = b2 // 256 ; b = b2 % 256
```
字符表：标准 base64 表 `A-Za-z0-9+/`（不含 `=` 填充）。

**颜色** = `r*65536 + g*256 + b`。

### 6.3 `pack_modes.py` 输出（多档）

```lua
local MD = {}
MD.POOL = 39853        -- 控件池（= 各档最大块数）
MD.BITS = 8
MD.N = 256             -- 兼容字段（第一档分辨率）
MD.MODES = {
  {std=1, src=256, n=39853, enc="b64", mae=0.27, data="..."},
  {std=0, src=200, n=36365, enc="b64", mae=0.00, data="..."},
}
```

| 字段 | 含义 |
|---|---|
| `POOL` | 需要预先创建的控件数（取各档最大 `n`） |
| `MODES[i].src` | 该档源分辨率（每档可不同） |
| `MODES[i].n` | 该档块数 |
| `MODES[i].enc` | 该档编码 |
| `MODES[i].mae` | 该档色差 |
| `MODES[i].data` | 该档块数据 |

---

## 7. 命令行接口（CLI）

```bash
# --- 压缩（最常用）---
python compress.py --input IMG --output OUT.lua --std S --size WxH
python compress.py --input IMG --output OUT.lua --std 0 --size 200x200      # 无损
python compress.py --input IMG --output OUT.lua --std 3 --size 300x300 --lock-aspect
python compress.py --input IMG --output OUT.lua --std 3 --enc hex            # 用 hex
python compress.py --config my.json

# --- 估算（选参数）---
python estimate.py --input IMG --size 300x300 --scan-std 0,1,2,3,4,6,8,12
python estimate.py --input IMG --scan-size 200,256,300 --std 3 --geometry-check
python estimate.py --input IMG --size 300x300 --std 3 --preview

# --- 多档打包 + 拼接 ---
python pack_modes.py --input IMG --specs 256:1,200:0 --out cmp.lua --preview
python assemble_modes.py cmp.lua render_modes.lua cmp_full.lua

# --- 自检 ---
python verify_toolkit.py
python verify_modes2.py
python selftest.py
node check_lua.js <某个.lua>
```

---

## 8. Python API（可直接 import）

```python
import sys
sys.path.insert(0, r"<工具包目录>")

from compress import load_and_prepare, quantize, pack_rects, validate_blocks, write_lua
from blockcodec import pack, sizes, check_scan_order, compute_mae, reconstruct

# 1) 载入 + 预处理（锁比例=False）
arr = load_and_prepare("a.png", 300, 300, lock_aspect=False)   # -> (H,W,3) int16

# 2) 量化（bits=8 时等于不量化）
q = quantize(arr, 8)

# 3) 矩形合并（std 任意 0~1024）
blocks = pack_rects(q, 3)          # -> [(x,y,w,h,color24), ...]

# 4) 自检
holes, overlap, oob = validate_blocks(blocks, 300, 300)   # 全 0 才正确
bad = check_scan_order(blocks, 300)                       # 必须 0（否则不能省坐标）

# 5) 画质
mae, maxerr = compute_mae(arr, blocks, 300, 300)

# 6) 编码 + 统计
data = pack(blocks, "b64")        # 或 "hex"
sz = sizes(blocks)                # {'b64_chars':..., 'hex_chars':..., ...}

# 7) 写出 lua
write_lua("out.lua", blocks, 300, 300, 3, 8, "b64", mae, var_name="IMG")
```

**返回值约定**
- `pack_rects` 返回的块**必须按扫描顺序**（列表顺序 = 扫描顺序）；不要打乱，否则坐标推演会错。
- `blocks[i] = (x, y, w, h, color24)`，`color24 = r<<16 | g<<8 | b`。

---

## 9. Lua 端接口（render.lua / render_modes.lua）

### 9.1 数据区替换（唯一需要手工/程序化做的事）

```
起始标记：local IMG = {}          （render_modes.lua 是 local MD = {}）
结束标记：-- ▲▲▲ 数据区结束 ▲▲▲
```

把这两个标记之间的内容整段替换为 `compress.py` 的输出（**不含 return**）。

程序化替换（Python）：
```python
data = open("out.lua", encoding="utf-8").read().strip()
tpl = open("render.lua", encoding="utf-8").read()
a = tpl.index("local IMG = {}")
b = tpl.index("-- ▲▲▲ 数据区结束 ▲▲▲")
open("deploy.lua", "w", encoding="utf-8").write(tpl[:a] + data + "\n" + tpl[b:])
```

### 9.2 render.lua 可调参数（RENDER 表）

| 参数 | 默认 | 说明 |
|---|---|---|
| `TEMPLATE` | `0` | 图片控件模板索引；**0 = 自动探测** |
| `TEMPLATE_PRIORITY` | `{1073741931, 1073758498, 1073741926}` | 优先尝试的模板 |
| `TEMPLATE_SCAN` | `{1073741800, 1073742100}` | 自动探测区间 |
| `UNIT` | `"AUTO"` | 每个源像素占多少画布单位；`"AUTO"` 按画布自适应；填数字则固定 |
| `MAX_RATIO` | `0.98` | 图最多占画布的比例 |
| `MARGIN_PX` | `0.20` | ★ 每块向外扩多少**源像素**（消除拼缝）。**必须与分辨率挂钩** |
| `MARGIN` | `nil` | 旧口径（固定画布单位，绝对值）。填了就优先用它；**高分辨率下会过度外扩造成毛边**，不建议再用 |
| `GROUPS` | `16` | ★ 显示分组数：建完每帧显示一组 |
| `BUDGET` | `0.040` | ★ 分帧建立每帧预算（秒）；`0` = 不分帧 |
| `BUDGET_CHECK` | `32` | 每这么多个块查一次时钟 |

> ★ **V1.1 起 `render.lua` 已实现「隐藏分组建立 → 建完分帧显示」**（本节 §9.2 与文档 §8.5 推荐的做法）：
> 控件挂在隐藏的全屏透明组下建立（稳态 1.7 µs/个 vs 可见态 15~18 µs/个，**约 9 倍**），
> 建立与"变可见"都分帧。所以**块数不再受"单次回调 20 s"的约束**，
> 真正要盯的是稳态帧率 = `15~18 µs × 可见控件数`。
> 隐藏/显示必须**冒号调用**（`c:SetVisible(false)` ✓ ／ `c.visible = false` ✗ 静默失败）；
> 脚本会把 pcall 结果打日志，若失败会显式报错并回退为全程可见。
| `RECT_IMG` | `100001` | 引擎内置纯色图 ID |
| `SHOW_CURSOR` | `true` | 显示鼠标 |
| `LOCK_CHARACTER` | `true` | 屏蔽按键穿透（WASD 不驱动角色） |

`render_modes.lua` 额外有：
| 参数 | 说明 |
|---|---|
| `SWITCH_KEY` | 切档按键的枚举名，默认 `"KeyboardCraftspersonKey18Down"`（= P） |
| `SHOW_TEXT` | 是否在顶部显示当前档位文字（复用关卡里的文本框模板） |

### 9.3 在千星奇域接入（**必须的编辑器操作**）

```
① 准备图片控件模板（一次性）
   界面控件组管理 → 界面布局 → 布局详情/自定义 → 点「客户端控件容器」
     → 右侧「画布设置」→【前往编辑】
     → 左下角【添加控件】→ 选「图片控件」
     → 选中它 → 【存为模板】
        ★ 必须存为「客户端控件模板」，不要存成服务器"元件/Prefab"（那是 3D 物件用的）
     → 保存

② 部署脚本
   把拼好的 render.lua 复制为 <脚本名>.lua，覆盖到
   <存档目录>/Beyond_Local_Save_Level/<关卡ID>/external_lua_file/<脚本名>.lua
   （<脚本名> 与关卡里挂载的脚本名一致；编辑器进关卡时会重新读取该文件）

③ 挂载脚本
   界面控件组管理 → 界面布局 → 布局详情/自定义 → 选中「客户端控件容器」
     → 挂载脚本 → 名字与文件名一致 → 保存 → 进关卡
```

### 9.4 成功日志样例

```
[render] ===== 最大对齐矩形合并压缩 · 渲染器 =====
[render] 画布 1599x899  宿主=ClientUIContainerControl:1
[render] 使用模板 = 1073741931
[render] 数据：300x300  30612 块  STD=3.0  ENC=b64  MAE=1.17
[render] 渲染完成：30612 个控件（失败 0），耗时 6.83 s
[render]   300x300 像素  编码=b64  块数=30612  压缩率=2.94x  MAE=1.17
[render]   UNIT=3.441  显示边长 881 单位（画布 1599x899）
[render] ===== 就绪 =====
```

---

## 10. 常见任务配方（Recipes）

### R1. 给定"控件预算"，找最佳参数

```bash
# 预算 30,000 控件：扫描 STD 与分辨率，挑块数 ≤ 30000 且 MAE 最小的一行
python estimate.py --input IMG --scan-size 200,256,300 --scan-std 1,2,3,4,6 --geometry-check
```

### R2. 完全不损失画质（无损）

```bash
python estimate.py --input IMG --size 200x200 --std 0        # 先看块数
python compress.py --input IMG --output out.lua --size 200x200 --std 0
```
`STD=0` 只合并颜色完全相同的相邻像素 → **MAE = 0.00**（无损），块数约为像素数的 0.9 倍。

### R3. 同一关卡内对比多组参数（游戏里按 P 切换）

```bash
python pack_modes.py --input IMG --specs 256:1,256:3,200:0 --out cmp.lua --preview
python assemble_modes.py cmp.lua render_modes.lua cmp_full.lua
# 部署 cmp_full.lua，进关卡按 P 切换
```
**注意**：多档的所有图像都会**显示为同一屏幕尺寸**（`UNIT="AUTO"`），便于公平对比。

### R4. 非正方形/锁定比例

```bash
python compress.py --input 宽图.png --output out.lua --size 300x300 --lock-aspect
```
`--lock-aspect` 会按比例缩放后居中放入 300×300（空白填白），不拉伸。
不加则直接拉伸（允许变形）。**注意**：`render.lua` 按正方形摆放，非正方形需自行调整。

### R5. 画面有细缝

```lua
-- render.lua 的 RENDER 表
MARGIN_PX = 0.35,   -- 从默认 0.20 提到 0.35（每边多扩 0.15 源像素）
```

### R6. 图太大/太小

```lua
UNIT = "AUTO",  -- 按画布自适应（推荐）
UNIT = 4,       -- 或固定：显示尺寸 = 边长 × UNIT（超出画布会自动缩小并打日志）
```

### R7. 换输入图 / 换关卡

- 换图：重跑 `compress.py`，重新替换数据区，覆盖部署
- 换关卡：把拼好的 lua 复制到新关卡的 `external_lua_file/`（**模板要在新关卡里重新创建**，见 §9.3 ①）

---

## 11. 故障排查表

| 症状 | 原因 | 解决 |
|---|---|---|
| **进关卡后完全无日志、无画面** | ① 输出带了 `return` 粘进数据区（§4.4）② 数据括号/语法错 ③ 表构造器过多（§4.3） | 跑 `python verify_toolkit.py`；`node check_lua.js 你的文件.lua` |
| 卡死 / 脚本反复重建 | 单次回调太久（>20 s） | ①开启动态 STD（默认已开）②提高 STD/降分辨率 ③**改用分帧创建** |
| 数据只处理了一部分（画面缺一块） | **解析超时被静默中断** | 把解码/解析也**分帧**（见 `大批量控件-分帧创建.md`） |
| `找不到可用的图片控件模板` | 关卡里没有"已存为客户端模板"的图片控件 | 按 §9.3 ① 创建；或在 `TEMPLATE` 里填实际索引 |
| 画面有发丝缝 | 外扩量太小 | 调大 `MARGIN_PX`（0.20 → 0.35 → 0.50）；仍不行再填 `MARGIN`（画布单位） |
| **画面有规律毛边/锯齿/平涂区出现斑驳纹理** | `MARGIN` 用了固定画布单位，高分辨率下过度外扩 | 改用 `MARGIN_PX`（源像素口径）；见 README 6.5 |
| 图超出画布/被裁 | UNIT 太大 | `UNIT = "AUTO"` |
| 画面糊/块状明显 | STD 太大 | 降低 STD（代价：控件数上升） |
| `块尺寸超过 255` | STD 极大导致巨块 | 降低 STD（编码用单字节存 w,h） |
| 坐标错乱/画面撕裂 | 有人打乱了块顺序（破坏扫描顺序） | `pack_rects` 的输出顺序不能改；用 `check_scan_order` 自检（须为 0） |
| `number has no integer representation` | 用 `%d` 格式化浮点数（Lua 5.3 特性） | 日志格式化统一用 `%.0f` 或先 `math.floor` |
| 无 Python 依赖 | 未安装 | `pip install pillow numpy` |

---

## 12. 自检命令（改代码后必跑）

```bash
python verify_toolkit.py     # 端到端：压缩 → 用 render.lua 的真实解码器解压 → 校验和比对
python verify_modes2.py      # 多档链路：pack_modes → assemble → render_modes 解码器
python selftest.py           # 基础：几何不变式、estimate/compress 一致性、Lua 语法
```

**期望输出结尾**：`✓ 全部通过` / `✓ 多档链路全部通过`。

`verify_toolkit.py` 的关键设计：它**从 render.lua 里抽取实际解码代码**来解压，
所以测的就是真正会运行的代码，而不是复制品。

---

## 13. 已实测数据（用于决策）

### 13.1 单控件成本（真实关卡实测）

| 操作 | 耗时 |
|---|---|
| 新建 1 个控件（完整设置） | **0.27 ms**（N 小时）；**随 N 上升**：N=20,000 时约 0.40 ms |
| 建立耗时模型 | `T(ms) = 0.27·N + 3.75e-6·N²`（**二次项是引擎内部的，无法规避**）|
| 仅 `Instantiate` | 0.197 ms（图片控件）/ 0.307 ms（文本控件） |
| 改 1 个控件属性 | **0.004 ~ 0.012 ms**（比新建快 **20 倍以上**） |
| **每帧渲染（可见控件）** | **15~18 µs/个**（5,000→12 fps，20,000→3 fps）★ 真正的天花板 |
| **每帧渲染（隐藏控件）** | **约 1.7 µs/个**；隐藏→显示后仍约 1.8 µs（**约 9 倍收益**）|

**结论**：
- 能"改属性"就不要"销毁重建"。切换/换图用改属性。
- **要建大批量控件 → 分帧创建 + 全程隐藏**（见 `大批量控件-分帧创建.md`）。
- **已实测排除**：分块挂载（曲线不变）、加大每帧批量（只快 1.4 倍）、控件复制（API 不存在）。

### 13.2 块数 ↔ 画质（300×300 插画，24 位真彩）

| STD | 块数（约） | MAE | 观感 |
|---|---|---|---|
| 0 | 78,000 | 0.00 | 无损（但控件超限） |
| 1 | 52,500 | 0.30 | 极佳（略超限） |
| 2 | 38,500 | 0.72 | 很好 |
| **3** | **31,871** | **1.07** | **推荐：几乎看不出** |
| 4 | 25,600 | 1.63 | 轻微 |
| 6 | 18,800 | 2.59 | 轻微块状 |
| 8 | 14,500 | 3.59 | 明显 |

> MAE 主要由 STD 决定（与图片内容关系较小）；**块数**与内容强相关（见 13.3）。

### 13.3 图片内容对压缩率的影响（300×300，STD=3）

| 图像类型 | 压缩率 |
|---|---|
| 纯几何色块 | ~968× |
| 灰度插画 | 3.8× |
| 浅色平涂插画 | 3.1× |
| 一般插画 | 2.9× |
| 深色高对比/多角色 | 2.5× |

**想省控件，优先选"平涂/几何/像素风"素材，而不是"降色数"。**

### 13.4 块数据体积（39,853 块实测）

| 编码 | 每块字符 | 总字符 | 相对 |
|---|---|---|---|
| 旧 Lua 表 `{x,y,w,h,c}` | ~36 | ~143 万 | — |
| hex（去坐标） | 10 | 39.9 万 | 28% |
| **b64（去坐标）** | **7** | **27.9 万** | **19%** |

> **b64 相对 hex 省 30%，相对旧表写法省 81%。**
> 且字符串编码把"表构造器数量"从 N 降到 1，规避了 §4.3 的编译期失败。

### 13.5 已验证的环境事实

| 事实 | 说明 |
|---|---|
| 引擎 Lua 是 **5.3+** | `string.format("%d", 浮点)` 会报错 |
| 整数宽度 | **不保证 64 位**（模拟器实测 32 位回绕）→ 编码须每步 < 2^24 |
| 画布（示例设备） | 1599 × 899 画布单位 |
| 画布单位 → 物理像素 | ×1.707（随设备变化） |
| base64 编码 | **已在真实关卡实测通过**（hex 与 b64 解码结果校验和完全一致） |
| b64 与坐标推演 | 已在真实关卡通过（校验和、面积和、几何全部一致） |

---

## 附：一句话总结

> **用 `estimate.py` 选参数（看块数与 MAE）→ 用 `compress.py` 压缩（默认 b64 编码）→
> 粘贴进 `render.lua` 数据区 → 部署到 `external_lua_file/` 进关卡。**
> 块数 ≤ 45,000（**单次回调**；更多请分帧创建）；动态 STD 默认开启（块数 −30~34%）；
> 不要用 Lua 表；输出不要带 `return`；编码运算不得超 2^24。

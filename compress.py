#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
 compress.py —— 最大对齐矩形合并压缩器（千星奇域 / 客户端控件像素渲染）
================================================================================

【这个脚本做什么】
  把一张图片压缩成"一组轴对齐纯色矩形（块）"，再把块列表编码成一个字符串，
  供 render.lua 在千星奇域里用客户端控件逐个矩形画出来。


【算法】
  1. 量化（可选，默认关闭）
     由 COLOR_BITS 控制每通道位数；8 = 24 位真彩、不量化。
     ⚠️ 实测：降位数会让误差变大但几乎不减少块数（反而可能增加）。
        除非有特殊需求，保持 COLOR_BITS = 8。

  2. 最大对齐矩形合并（核心）
     按行主序扫描每个未占用的像素 (i, j)：
       a. 向右扩宽 w：要求当前行 [i, i+w) 内三通道极差 ≤ STD 且都未占用
       b. 向下扩高 h：要求矩形内所有像素未占用，且整个 w×h 矩形标准差 ≤ STD
       c. 取"面积最大"的 (w, h) 作为一块
       d. 标记占用，块色 = 区域内三通道均值
     · 用积分图让"任意矩形的均值/方差"为 O(1)
     · 矩形边界都落在整数像素坐标上 → 拼接无缝
     · 块列表按扫描顺序输出 → 渲染端可由扫描推演还原 x,y（见下）

  3. 块列表编码（blockcodec.py）
     · 坐标 x,y 不存储，由扫描顺序推演（省 29%）
     · 两种编码可选：
         hex：10 字符/块（可肉眼调试）
         b64： 7 字符/块（比 hex 再省 30%）← 已实测通过
     · ★ 为什么不用 Lua 表 {{x,y,w,h,c},...}：
         每个块 = 1 个表构造器。实测 6.2 万构造器 / 1.23 MB 正常，
         8.9 万构造器 / 2.01 MB 会让引擎完全无日志（编译期失败）。
         字符串编码把构造器数量降到 1 个，彻底规避该风险。

  4. 输出：Lua 数据表（见 render.lua 的数据区）


【配置方式】—— 改下面 CONFIG 区，或命令行覆盖（命令行 > JSON > CONFIG）

  STD         合并容差，**0 ~ 1024 任意值**（不再限制为固定档位）
              0   = 只合并颜色完全相同的相邻像素 → 无损（MAE = 0）
              小值 = 几乎无损；大值 = 块更少但更糊
              经验：MAE ≤ 1.5 一般人看不出；≥ 3.5 明显
              参考（300×300 插画）：STD=3 → MAE≈1.2、块数≈3 万
  OUT_W/OUT_H 输出分辨率（源像素数）
  LOCK_ASPECT True=按原图比例缩放后居中放入（不拉伸，空白填白）
              False=直接拉伸到 OUT_W×OUT_H（允许变形）
  COLOR_BITS  每通道位数，8 = 24 位真彩（推荐）
  ENC         块列表编码："b64"（默认，最省）或 "hex"（可肉眼查看）
  INPUT/OUTPUT 输入图片 / 输出 lua 路径
  PREVIEW     是否输出重建预览图
  MAX_BLOCKS  块数告警阈值（超过只警告）


【命令行】
  python compress.py --input a.png --output a.lua --std 3 --size 300x300
  python compress.py --std 0 --size 200x200            # 无损（逐像素）
  python compress.py --enc hex                          # 用 hex 编码
  python compress.py --lock-aspect                      # 锁定长宽比
  python compress.py --preview                          # 输出重建预览
  python compress.py --config config.json


【输出格式】（给 render.lua）
  local IMG = {}
  IMG.N    = 300          -- 边长（正方形）
  IMG.W    = 300          -- 逻辑宽
  IMG.H    = 300          -- 逻辑高
  IMG.STD  = 3            -- 使用的容差
  IMG.ENC  = "b64"        -- 编码："b64" | "hex"
  IMG.NBLK = 30612        -- 块数 = 需要的控件数
  IMG.MAE  = 1.17         -- 矩形合并的平均绝对色差（0~255，每通道）
  IMG.DATA = "..."        -- 编码后的块数据（解码方式见 render.lua）

  块数据编码（x,y 由扫描推演，不存储）：
    hex：每块 10 个 hex 字符 = w,h,r,g,b（各 1 字节）
    b64：每块 7 个字符 = [3 字节 w,h,r → 4 字符][2 字节 g,b → 3 字符]
  color = r*65536 + g*256 + b


【依赖】Python 3.8+，Pillow，numpy      pip install pillow numpy

【配套文件】
  render.lua      千星奇域渲染器（读本脚本输出）
  pack_modes.py   同图多档打包（对比不同 STD / 分辨率）
  render_modes.lua 多档切换渲染器
  estimate.py     只估算控件数与 MAE
  blockcodec.py   编解码实现（本脚本与 pack_modes.py 共用）
  AGENT_GUIDE.md  ★ 面向 agent 的完整使用说明（先读它）
  README.md       完整文档
================================================================================
"""

import argparse
import json
import math
import os
import sys
import time
from typing import List, Tuple

try:
    import numpy as np
    from PIL import Image
except ImportError:
    print("缺少依赖，请先安装：pip install pillow numpy", file=sys.stderr)
    raise

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from blockcodec import (pack as codec_pack, sizes as codec_sizes,   # noqa: E402
                        check_scan_order, compute_mae, reconstruct)


# ==============================================================================
# 【配置区】—— 直接改这里，或命令行覆盖
# ==============================================================================
CONFIG = {
    "STD": 3,                  # 合并容差，0 ~ 1024 任意值（0 = 无损）
    "OUT_W": 300,              # 输出宽（源像素）
    "OUT_H": 300,              # 输出高（源像素）
    "LOCK_ASPECT": False,      # True=锁定长宽比（不拉伸），False=允许变形
    "COLOR_BITS": 8,           # 每通道位数，8=24 位真彩（不量化）
    "ENC": "b64",              # 块列表编码："b64"（最省）| "hex"（可肉眼查看）
    "INPUT": "input.png",      # 输入图片路径
    "OUTPUT": "output.lua",    # 输出 lua 路径
    "PREVIEW": False,          # 是否输出重建预览图
    "MAX_BLOCKS": 50000,       # 块数告警阈值 = 【OnStart 单次回调的推荐上限】
                               #   ≤50000 → 推荐 OnStart 一次建完 ✓（更快更简单）
                               #   > 50000 → 必须分帧创建（见 README 8.5 节）
    "VAR_NAME": "IMG",         # 输出的 Lua 变量名
    "WITH_RETURN": False,      # 是否在末尾加 return（直接粘进 render.lua 时不要）
    "MAX_DIM": 255,            # ★ 单个块的 w/h 上限（编码用单字节存 w,h，绝不能超 255）

    # ---------------- 动态 STD（★ 默认开启）----------------
    # 原理：细节区用最严的 STD、平坦区用更松的 STD。
    #       实测在【细节区 MAE 与全局 STD 持平】的前提下，块数减少 30~34%。
    # 六个参数全部可手动指定；任何一项为 None 时按 STD 自动推导：
    #     t1_std   = STD        t2_std = 2×STD      flat_std = 3×STD
    #     t1       = 30         t2     = 12         flat     = t2
    "DYN_STD": True,           # ★ 动态 STD 总开关（False = 退回全局 STD，行为与旧版一致）
    "T1_STD": None,            # 细节区容差   None = 自动 = STD
    "T2_STD": None,            # 过渡区容差   None = 自动 = 2×STD
    "FLAT_STD": None,          # 平坦区容差   None = 自动 = 3×STD
    "T1": 30.0,                # 细节判定阈值（梯度 > T1 → 用 t1_std）
    "T2": 12.0,                # 过渡判定阈值（T2 < 梯度 ≤ T1 → 用 t2_std）
    "FLAT": None,              # 平坦区上界   None = 自动 = T2（梯度 ≤ flat → 用 flat_std）
    "DYN_M2": 2.0,             # 自动时 t2_std = DYN_M2 × STD
    "DYN_M3": 3.0,             # 自动时 flat_std = DYN_M3 × STD
    "DYN_R": 2,                # 容差图平滑半径（越大细节区越厚、块数越多但越安全）
    # 注：DYN_STD=False 或 STD=0（无损）时自动关闭动态 STD
}
# ==============================================================================

STD_MIN, STD_MAX = 0.0, 1024.0

# ★ 单个块的 w/h 上限。编码用单字节存 w,h，超过 255 会静默回绕、画面被静默画错。
#   限制在【贪心生长过程内】而不是事后切块 —— 事后切会破坏"扫描顺序可推演 x,y"的约定。
MAX_DIM = 255

# 单次回调「建立控件」的实测成本模型（秒）
#   实测：5,000 → 1.35 s（0.270 ms/个）；10,000 → 2.71 s（0.271）；20,000 → 8.06 s（0.403）
#   拟合：每控件耗时 = 0.27 + 3.75e-6 × 已有控件数 (ms)  → 总量 T = 0.27N + 3.75e-6·N²
#   引擎单次回调上限约 20 s（超时日志 "Lua execution took too long" 并中断脚本）
MS_PER_CTL = 0.27
QUAD_COEF = 3.75e-6


def est_build_t(n: int) -> float:
    """单次回调建完 n 个控件的预估耗时（秒）"""
    return (MS_PER_CTL * n + QUAD_COEF * n * n) / 1000.0


# ------------------------------------------------------------------------------
# 图像载入与预处理
# ------------------------------------------------------------------------------
def load_and_prepare(path: str, out_w: int, out_h: int, lock_aspect: bool) -> np.ndarray:
    """读图 → 缩放/填充到 out_w×out_h → 返回 (H, W, 3) int16 数组"""
    if not os.path.exists(path):
        raise FileNotFoundError("找不到输入图片：%s" % path)

    im = Image.open(path).convert("RGB")
    ow, oh = im.size

    if lock_aspect:
        scale = min(out_w / ow, out_h / oh)
        nw, nh = max(1, int(round(ow * scale))), max(1, int(round(oh * scale)))
        resized = im.resize((nw, nh), Image.LANCZOS)
        canvas = Image.new("RGB", (out_w, out_h), (255, 255, 255))
        canvas.paste(resized, ((out_w - nw) // 2, (out_h - nh) // 2))
        out = canvas
    else:
        out = im.resize((out_w, out_h), Image.LANCZOS)

    return np.asarray(out).astype(np.int16)


def quantize(arr: np.ndarray, bits: int) -> np.ndarray:
    """每通道量化到 2^bits 级（带四舍五入）。bits>=8 时原样返回。"""
    if bits >= 8:
        return arr.copy()
    step = 1 << (8 - bits)
    half = step >> 1
    return np.clip(((arr + half) // step) * step, 0, 255).astype(np.int16)


# ------------------------------------------------------------------------------
# 积分图（任意矩形的均值/标准差 O(1)）
# ------------------------------------------------------------------------------
class Integrals:
    def __init__(self, arr: np.ndarray):
        self.H, self.W, _ = arr.shape
        H, W = self.H, self.W
        self.S = np.zeros((3, H + 1, W + 1), dtype=np.float64)
        self.S2 = np.zeros((3, H + 1, W + 1), dtype=np.float64)
        for ch in range(3):
            v = arr[:, :, ch].astype(np.float64)
            self.S[ch, 1:, 1:] = v.cumsum(0).cumsum(1)
            self.S2[ch, 1:, 1:] = (v * v).cumsum(0).cumsum(1)

    @staticmethod
    def _rect(A, x, y, w, h):
        return A[y + h, x + w] - A[y, x + w] - A[y + h, x] + A[y, x]

    def std(self, x: int, y: int, w: int, h: int) -> float:
        n = w * h
        m = 0.0
        for ch in range(3):
            s1 = self._rect(self.S[ch], x, y, w, h)
            s2 = self._rect(self.S2[ch], x, y, w, h)
            mean = s1 / n
            var = s2 / n - mean * mean
            if var > 0:
                v = math.sqrt(var)
                if v > m:
                    m = v
        return m

    def mean(self, x: int, y: int, w: int, h: int) -> Tuple[int, int, int]:
        n = w * h
        return tuple(int(round(self._rect(self.S[ch], x, y, w, h) / n)) for ch in range(3))


# ------------------------------------------------------------------------------
# 核心：最大对齐矩形合并
# ------------------------------------------------------------------------------
def pack_rects(arr: np.ndarray, std_tol: float,
               max_dim: int = MAX_DIM) -> List[Tuple[int, int, int, int, int]]:
    """
    划分为最少数量的、颜色变化在容差内的、轴对齐矩形。
    返回 [(x, y, w, h, color24), ...]，**按行主序扫描顺序**（供扫描推演还原坐标）。

    std_tol = 0 表示只合并颜色完全相同的相邻像素（无损）。
    max_dim = 单个块 w/h 的上限（默认 255，因为编码用单字节存 w,h）。
              ★ 上限必须在生长过程中生效，不能事后切块 —— 否则破坏扫描顺序。
    """
    img = Integrals(arr)
    W, H = img.W, img.H
    used = np.zeros((H, W), dtype=bool)
    out: List[Tuple[int, int, int, int, int]] = []

    for j in range(H):
        uj = used[j]
        for i in range(W):
            if uj[i]:
                continue

            # ① 向右扩宽（本行内极差 ≤ tol 且未占用，且不超过 max_dim）
            w = 1
            while i + w < W and not uj[i + w] and w < max_dim:
                if img.std(i, j, w + 1, 1) > std_tol:
                    break
                w += 1

            # ② 向下扩高：颜色允许高度 与 占用允许高度 取小（都不超过 max_dim）
            h_color = 1
            while j + h_color < H and h_color < max_dim:
                if img.std(i, j, w, h_color + 1) > std_tol:
                    break
                h_color += 1
            h_free = 1
            while j + h_free < H and h_free < max_dim:
                if used[j + h_free, i:i + w].any():
                    break
                h_free += 1
            h = min(h_color, h_free)

            # ③ 局部优化：尝试收窄宽度换取更大高度
            best_w, best_h, best_area = w, h, w * h
            w2 = w
            while w2 > 1:
                w2 -= 1
                hc = 1
                while j + hc < H and hc < max_dim:
                    if img.std(i, j, w2, hc + 1) > std_tol:
                        break
                    hc += 1
                hf = 1
                while j + hf < H and hf < max_dim:
                    if used[j + hf, i:i + w2].any():
                        break
                    hf += 1
                hh = min(hc, hf)
                if w2 * hh > best_area:
                    best_w, best_h, best_area = w2, hh, w2 * hh

            bw, bh = best_w, best_h
            used[j:j + bh, i:i + bw] = True
            r, g, b = img.mean(i, j, bw, bh)
            out.append((i, j, bw, bh, (r << 16) | (g << 8) | b))

    return out


# ------------------------------------------------------------------------------
# ★ 动态 STD（默认开启）
# ------------------------------------------------------------------------------
#  动机
#    全局 STD 对整幅图用同一个容差：平坦区（占大头）被浪费、细节区又不够锐利。
#    实测（300×300 插画，细节区 MAE 与全局 STD=S 持平的前提下）：
#         S=1 → 块数 −30.1%     S=2 → −33.2%     S=3 → −33.7%
#    即【画质不变，块数砍掉三成】。
#
#  两个关键设计
#    ① 容差按【局部梯度】三级分档：细节区最严、平坦区最松
#    ② 矩形生长时取【覆盖区内最小容差】作为判据
#       —— 否则从平坦区长出的大矩形会把细节吃掉
#          （实测只取锚点容差时，细节区 MAE 从 0.050 恶化到 0.094）
# ------------------------------------------------------------------------------

def auto_dyn_params(std: float, t1=None, t2=None, flat=None,
                    t1_std=None, t2_std=None, flat_std=None,
                    m2: float = 2.0, m3: float = 3.0, r: int = 2) -> dict:
    """
    由「用户选择的压缩 STD」自动补全动态 STD 的六个参数。
    任何一项显式给出时以显式值为准（保留手动接口）。

    返回 dict: t1, t2, flat, t1_std, t2_std, flat_std, r
    """
    S = float(std)
    P = {
        "t1": 30.0 if t1 is None else float(t1),
        "t2": 12.0 if t2 is None else float(t2),
        "t1_std": S if t1_std is None else float(t1_std),
        "t2_std": S * float(m2) if t2_std is None else float(t2_std),
        "flat_std": S * float(m3) if flat_std is None else float(flat_std),
        "r": int(r),
    }
    P["flat"] = P["t2"] if flat is None else float(flat)
    return P


def build_tolmap(arr: np.ndarray, P: dict) -> np.ndarray:
    """
    按参数表构造逐像素容差图 (H, W)。

    分级规则（梯度 g 为水平/垂直差分的较大者，再做半径 r 的方框平滑）：
        g > t1            → t1_std     （细节区）
        flat < g ≤ t1     → t2_std     （过渡区）
        g ≤ flat          → flat_std   （平坦区）
    默认 flat == t2，即退化为常见的三级分档。
    """
    f = arr.astype(np.float64)
    lum = 0.299 * f[:, :, 0] + 0.587 * f[:, :, 1] + 0.114 * f[:, :, 2]
    dx = np.zeros_like(lum)
    dy = np.zeros_like(lum)
    dx[:, 1:] = np.abs(np.diff(lum, axis=1))
    dy[1:, :] = np.abs(np.diff(lum, axis=0))
    g = np.maximum(dx, dy)

    r = max(0, int(P["r"]))
    if r > 0:                                   # 方框平滑（积分图实现，O(1)/像素）
        H, W = g.shape
        pad = np.zeros((H + 1, W + 1), dtype=np.float64)
        pad[1:, 1:] = g.cumsum(0).cumsum(1)
        y0 = np.clip(np.arange(H) - r, 0, H)[:, None]
        y1 = np.clip(np.arange(H) + r + 1, 0, H)[:, None]
        x0 = np.clip(np.arange(W) - r, 0, W)[None, :]
        x1 = np.clip(np.arange(W) + r + 1, 0, W)[None, :]
        s = pad[y1, x1] - pad[y0, x1] - pad[y1, x0] + pad[y0, x0]
        n = (y1 - y0) * (x1 - x0)
        g = s / np.maximum(1, n)

    tol = np.full(g.shape, float(P["flat_std"]), dtype=np.float64)
    tol[g > P["flat"]] = float(P["t2_std"])
    tol[g > P["t2"]] = float(P["t2_std"])
    tol[g > P["t1"]] = float(P["t1_std"])
    return tol


def pack_rects_dyn(arr: np.ndarray, tolmap: np.ndarray,
                   use_min: bool = True,
                   max_dim: int = MAX_DIM) -> List[Tuple[int, int, int, int, int]]:
    """
    带【逐像素容差图】的最大对齐矩形合并。

    与 pack_rects 结构完全一致（行主序扫描、同样的三小步、同样的输出顺序），
    因此输出仍然满足"扫描顺序可推演 x,y"的约定（check_scan_order 会自检）。

    use_min=True 时取矩形覆盖区内的最小容差作为判据（★ 推荐，防止吃掉细节）。
    max_dim = 单个块 w/h 的上限（默认 255，理由同 pack_rects）。
    """
    img = Integrals(arr)
    W, H = img.W, img.H
    used = np.zeros((H, W), dtype=bool)
    out: List[Tuple[int, int, int, int, int]] = []

    for j in range(H):
        uj = used[j]
        for i in range(W):
            if uj[i]:
                continue
            base = float(tolmap[j, i])

            # ① 向右扩宽（本行内标准差在容差内且未占用，且不超过 max_dim）
            w = 1
            mt = base
            while i + w < W and not uj[i + w] and w < max_dim:
                nt = min(mt, float(tolmap[j, i + w])) if use_min else base
                if img.std(i, j, w + 1, 1) > nt:
                    break
                mt = nt
                w += 1

            # ② 向下扩高：颜色允许高度 与 占用允许高度 取小（都不超过 max_dim）
            h_color = 1
            mtc = mt
            while j + h_color < H and h_color < max_dim:
                nt = min(mtc, float(tolmap[j + h_color, i:i + w].min())) if use_min else base
                if img.std(i, j, w, h_color + 1) > nt:
                    break
                mtc = nt
                h_color += 1
            h_free = 1
            while j + h_free < H and h_free < max_dim:
                if used[j + h_free, i:i + w].any():
                    break
                h_free += 1
            h = min(h_color, h_free)

            # ③ 局部优化：尝试收窄宽度换取更大高度
            best_w, best_h, best_area = w, h, w * h
            w2 = w
            while w2 > 1:
                w2 -= 1
                mt2 = float(tolmap[j, i:i + w2].min()) if use_min else base
                hc = 1
                while j + hc < H and hc < max_dim:
                    nt = min(mt2, float(tolmap[j + hc, i:i + w2].min())) if use_min else base
                    if img.std(i, j, w2, hc + 1) > nt:
                        break
                    hc += 1
                hf = 1
                while j + hf < H and hf < max_dim:
                    if used[j + hf, i:i + w2].any():
                        break
                    hf += 1
                hh = min(hc, hf)
                if w2 * hh > best_area:
                    best_w, best_h, best_area = w2, hh, w2 * hh

            bw, bh = best_w, best_h
            used[j:j + bh, i:i + bw] = True
            r, g, b = img.mean(i, j, bw, bh)
            out.append((i, j, bw, bh, (r << 16) | (g << 8) | b))

    return out


def pack_auto(arr: np.ndarray, std: float, dyn: bool = True, params_override: dict = None,
              max_dim: int = MAX_DIM):
    """
    统一入口：按需选择「动态 STD」或「全局 STD」。
    返回 (blocks, info) —— info 里带本次实际使用的参数（便于日志/回显）。
    """
    if (not dyn) or float(std) <= 0.0:
        return pack_rects(arr, std, max_dim=max_dim), {"mode": "global", "std": float(std)}
    P = auto_dyn_params(std, **(params_override or {}))
    tol = build_tolmap(arr, P)
    blocks = pack_rects_dyn(arr, tol, use_min=True, max_dim=max_dim)
    info = dict(P)
    info["mode"] = "dynamic"
    info["std"] = float(std)
    info["share"] = {
        "t1": float((tol == P["t1_std"]).mean()),
        "t2": float((tol == P["t2_std"]).mean()),
        "flat": float((tol == P["flat_std"]).mean()),
    }
    return blocks, info


# ------------------------------------------------------------------------------
# 几何自检
# ------------------------------------------------------------------------------
def validate_blocks(blocks, W: int, H: int) -> Tuple[int, int, int]:
    """返回 (空洞数, 重叠数, 越界数) —— 三者都应为 0"""
    cover = np.zeros((H, W), dtype=np.int32)
    oob = 0
    for (x, y, w, h, c) in blocks:
        if x < 0 or y < 0 or x + w > W or y + h > H or w <= 0 or h <= 0:
            oob += 1
            continue
        cover[y:y + h, x:x + w] += 1
    holes = int((cover == 0).sum())
    overlap = int((cover > 1).sum())
    return holes, overlap, oob


# ------------------------------------------------------------------------------
# 输出
# ------------------------------------------------------------------------------
def write_lua(path: str, blocks, W: int, H: int, std: float, bits: int, enc: str,
              mae: float, var_name: str = "IMG", with_return: bool = False,
              dyn_info: dict = None) -> None:
    """
    输出配套 render.lua 的 Lua 数据表。

    ★ with_return 默认 False —— 输出通常要【直接粘进 render.lua 的数据区】，
      而 Lua 规定 return 必须是块的最后一条语句，粘在中间会编译失败
      （报 '<eof>' expected near 'local'，表现为进关卡后无日志无画面）。
    """
    data = codec_pack(blocks, enc)
    mode = (dyn_info or {}).get("mode", "global")
    lines = [
        "-- 由 compress.py 生成（最大对齐矩形合并压缩）",
        "-- STD=%s  COLOR_BITS=%d  分辨率=%dx%d  编码=%s  块数=%d  MAE=%.2f  模式=%s"
        % (std, bits, W, H, enc, len(blocks), mae,
           "动态STD" if mode == "dynamic" else "全局STD"),
        "-- 用法：把本文件【全部内容】替换进 render.lua 的『数据区』",
        "local %s = {}" % var_name,
        "%s.N = %d" % (var_name, W),
        "%s.W = %d" % (var_name, W),
        "%s.H = %d" % (var_name, H),
        "%s.STD = %s" % (var_name, std),
        "%s.DYN = %s" % (var_name, "true" if mode == "dynamic" else "false"),
        "%s.ENC = \"%s\"" % (var_name, enc),
        "%s.NBLK = %d" % (var_name, len(blocks)),
        "%s.MAE = %.2f" % (var_name, mae),
    ]
    if mode == "dynamic" and dyn_info:
        lines.insert(3, "-- 动态 STD 参数：t1=%(t1)g t2=%(t2)g flat=%(flat)g | "
                        "t1_std=%(t1_std)g t2_std=%(t2_std)g flat_std=%(flat_std)g | r=%(r)d"
                     % dyn_info)
        lines.append("%s.DYN_T1 = %g" % (var_name, dyn_info.get("t1", 0)))
        lines.append("%s.DYN_T2 = %g" % (var_name, dyn_info.get("t2", 0)))
        lines.append("%s.DYN_FLAT = %g" % (var_name, dyn_info.get("flat", 0)))
        lines.append("%s.DYN_T1_STD = %g" % (var_name, dyn_info.get("t1_std", 0)))
        lines.append("%s.DYN_T2_STD = %g" % (var_name, dyn_info.get("t2_std", 0)))
        lines.append("%s.DYN_FLAT_STD = %g" % (var_name, dyn_info.get("flat_std", 0)))
    lines.append("%s.DATA = \"%s\"" % (var_name, data))
    if with_return:
        lines.append("return %s" % var_name)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


# ------------------------------------------------------------------------------
# 主流程
# ------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description="最大对齐矩形合并压缩器（输出千星奇域可渲染的 Lua 块数据）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n"
               "  python compress.py --input a.png --output a.lua --std 3 --size 300x300\n"
               "  python compress.py --std 0 --size 200x200        # 无损\n"
               "  python compress.py --enc hex                     # 用 hex 编码\n")
    ap.add_argument("--input", help="输入图片路径")
    ap.add_argument("--output", help="输出 lua 路径")
    ap.add_argument("--std", type=float, help="合并容差，0~1024 任意值（0=无损）")
    ap.add_argument("--dyn-std", dest="dyn_std", action="store_true", default=None,
                    help="开启动态 STD（默认已开启）")
    ap.add_argument("--no-dyn-std", dest="dyn_std", action="store_false",
                    help="关闭动态 STD（退回全局 STD，行为与旧版一致）")
    ap.add_argument("--t1-std", type=float, help="动态STD·细节区容差（默认=STD）")
    ap.add_argument("--t2-std", type=float, help="动态STD·过渡区容差（默认=2×STD）")
    ap.add_argument("--flat-std", type=float, help="动态STD·平坦区容差（默认=3×STD）")
    ap.add_argument("--t1", type=float, help="动态STD·细节判定阈值（默认30）")
    ap.add_argument("--t2", type=float, help="动态STD·过渡判定阈值（默认12）")
    ap.add_argument("--flat", type=float, help="动态STD·平坦区上界（默认=T2）")
    ap.add_argument("--dyn-m2", type=float, help="自动时 t2_std 倍数（默认2）")
    ap.add_argument("--dyn-m3", type=float, help="自动时 flat_std 倍数（默认3）")
    ap.add_argument("--dyn-r", type=int, help="容差图平滑半径（默认2）")
    ap.add_argument("--size", help="输出分辨率，形如 300x300")
    ap.add_argument("--lock-aspect", action="store_true", help="锁定长宽比（不拉伸）")
    ap.add_argument("--no-lock-aspect", action="store_true", help="允许变形（默认）")
    ap.add_argument("--bits", type=int, help="每通道位数，8=24 位真彩（推荐）")
    ap.add_argument("--enc", choices=["b64", "hex"], help="块列表编码：b64（最省）/ hex")
    ap.add_argument("--preview", action="store_true", help="输出重建预览图")
    ap.add_argument("--max-blocks", type=int, help="块数告警阈值")
    ap.add_argument("--var-name", help="输出 Lua 变量名（默认 IMG）")
    ap.add_argument("--with-return", action="store_true",
                    help="在输出末尾加 return（仅当把输出当独立 Lua 模块用时；"
                         "直接粘进 render.lua 时不要加）")
    ap.add_argument("--config", help="JSON 配置文件")
    args = ap.parse_args()

    cfg = dict(CONFIG)
    if args.config:
        with open(args.config, encoding="utf-8") as f:
            cfg.update(json.load(f))
    if args.input: cfg["INPUT"] = args.input
    if args.output: cfg["OUTPUT"] = args.output
    if args.std is not None: cfg["STD"] = args.std
    if args.size:
        w, h = args.size.lower().split("x")
        cfg["OUT_W"], cfg["OUT_H"] = int(w), int(h)
    if args.lock_aspect: cfg["LOCK_ASPECT"] = True
    if args.no_lock_aspect: cfg["LOCK_ASPECT"] = False
    if args.bits is not None: cfg["COLOR_BITS"] = args.bits
    if args.enc: cfg["ENC"] = args.enc
    if args.preview: cfg["PREVIEW"] = True
    if args.max_blocks is not None: cfg["MAX_BLOCKS"] = args.max_blocks
    if args.var_name: cfg["VAR_NAME"] = args.var_name
    if args.dyn_std is not None: cfg["DYN_STD"] = args.dyn_std
    if args.t1_std is not None: cfg["T1_STD"] = args.t1_std
    if args.t2_std is not None: cfg["T2_STD"] = args.t2_std
    if args.flat_std is not None: cfg["FLAT_STD"] = args.flat_std
    if args.t1 is not None: cfg["T1"] = args.t1
    if args.t2 is not None: cfg["T2"] = args.t2
    if args.flat is not None: cfg["FLAT"] = args.flat
    if args.dyn_m2 is not None: cfg["DYN_M2"] = args.dyn_m2
    if args.dyn_m3 is not None: cfg["DYN_M3"] = args.dyn_m3
    if args.dyn_r is not None: cfg["DYN_R"] = args.dyn_r

    std = float(cfg["STD"])
    if std < STD_MIN or std > STD_MAX:
        print("错误：STD 必须在 %s ~ %s 之间（你给了 %s）"
              % (STD_MIN, STD_MAX, std), file=sys.stderr)
        return 1

    enc = cfg["ENC"]
    print("=" * 78)
    print("最大对齐矩形合并压缩")
    print("=" * 78)
    print("  输入      : %s" % cfg["INPUT"])
    print("  输出      : %s" % cfg["OUTPUT"])
    print("  分辨率    : %d x %d" % (cfg["OUT_W"], cfg["OUT_H"]))
    print("  锁定比例  : %s" % cfg["LOCK_ASPECT"])
    print("  STD 容差  : %s%s" % (std, "（无损：只合并同色相邻像素）" if std == 0 else ""))
    use_dyn = bool(cfg.get("DYN_STD", True)) and std > 0
    print("  动态 STD  : %s" % ("★ 开启（参数由 STD 自动推导）" if use_dyn
                                else "关闭（全图统一容差）"))
    print("  颜色位数  : %d%s" % (cfg["COLOR_BITS"],
        "（24 位真彩，不量化）" if cfg["COLOR_BITS"] >= 8 else ""))
    print("  块列表编码: %s" % enc)

    t0 = time.time()
    arr = load_and_prepare(cfg["INPUT"], cfg["OUT_W"], cfg["OUT_H"], cfg["LOCK_ASPECT"])
    q = quantize(arr, cfg["COLOR_BITS"])
    print("  图像载入+预处理: %.2f s" % (time.time() - t0))

    if cfg["OUT_W"] != cfg["OUT_H"]:
        print("  注意：输出为非正方形（%dx%d）；render.lua 按正方形摆放块。"
              % (cfg["OUT_W"], cfg["OUT_H"]), file=sys.stderr)

    t0 = time.time()
    override = {
        "t1": cfg.get("T1"), "t2": cfg.get("T2"), "flat": cfg.get("FLAT"),
        "t1_std": cfg.get("T1_STD"), "t2_std": cfg.get("T2_STD"),
        "flat_std": cfg.get("FLAT_STD"),
        "m2": cfg.get("DYN_M2", 2.0), "m3": cfg.get("DYN_M3", 3.0),
        "r": cfg.get("DYN_R", 2),
    }
    override = {k: v for k, v in override.items() if v is not None}
    blocks, dyn_info = pack_auto(q, std, dyn=use_dyn, params_override=override,
                                 max_dim=int(cfg.get("MAX_DIM", MAX_DIM)))
    pack_t = time.time() - t0
    nblk = len(blocks)
    if dyn_info.get("mode") == "dynamic":
        print("  ---- 动态 STD 参数 ----")
        print("  梯度阈值  : t1=%(t1)g（>t1 → 细节区）   t2=%(t2)g（>t2 → 过渡区）   "
              "flat=%(flat)g（≤flat → 平坦区）" % dyn_info)
        print("  分区容差  : t1_std=%(t1_std)g   t2_std=%(t2_std)g   flat_std=%(flat_std)g"
              "   r=%(r)d" % dyn_info)
        sh = dyn_info.get("share", {})
        print("  区域占比  : 细节 %.1f%%   过渡 %.1f%%   平坦 %.1f%%"
              % (sh.get("t1", 0) * 100, sh.get("t2", 0) * 100, sh.get("flat", 0) * 100))

    # ---- 自检 1：几何（完整覆盖、不重叠、不越界）----
    holes, overlap, oob = validate_blocks(blocks, cfg["OUT_W"], cfg["OUT_H"])
    geo_ok = (holes == 0 and overlap == 0 and oob == 0)

    # ---- 自检 2：扫描顺序（决定 x,y 能否省略）----
    order_bad = check_scan_order(blocks, cfg["OUT_W"])
    order_ok = (order_bad == 0)

    # ---- 自检 3：块尺寸（★ 编码用单字节存 w,h，超过 255 会静默回绕画错图）----
    max_w = max((b[2] for b in blocks), default=0)
    max_h = max((b[3] for b in blocks), default=0)
    max_dim = int(cfg.get("MAX_DIM", MAX_DIM))
    dim_ok = (max_w <= max_dim and max_h <= max_dim)

    # ---- MAE（矩形合并造成的色差）----
    mae_q, maxerr_q = compute_mae(q, blocks, cfg["OUT_W"], cfg["OUT_H"])
    mae_orig, maxerr_orig = compute_mae(arr, blocks, cfg["OUT_W"], cfg["OUT_H"])

    # ---- 编码体积对比（明确告知能省多少）----
    sz = codec_sizes(blocks)
    print()
    print("  压缩耗时  : %.2f s" % pack_t)
    print("  块数      : %d  （= 需要的控件数）" % nblk)
    print("  最大块尺寸: %d x %d  （上限 %d）" % (max_w, max_h, max_dim))
    print("  压缩率    : %.2fx" % ((cfg["OUT_W"] * cfg["OUT_H"]) / max(1, nblk)))
    print("  平均块面积: %.1f 像素" % ((cfg["OUT_W"] * cfg["OUT_H"]) / max(1, nblk)))
    print("  ---- 画质（矩形合并误差）----")
    print("  MAE       : %.2f （最大单点误差 %d）  %s"
          % (mae_orig, maxerr_orig,
             "无损" if mae_orig == 0 else
             ("几乎无损" if mae_orig <= 1.5 else
              ("轻微" if mae_orig <= 3.0 else "可见块状"))))
    if cfg["COLOR_BITS"] < 8:
        print("  （其中量化贡献 %.2f，合并贡献 %.2f）"
              % (max(0.0, mae_orig - mae_q), mae_q))
    print("  ---- 块数据体积（编码方式可省空间）----")
    print("  hex       : %d 字符（%.1f 万）" % (sz["hex_chars"], sz["hex_chars"] / 10000))
    print("  b64       : %d 字符（%.1f 万）  相对 hex 省 %.0f%%"
          % (sz["b64_chars"], sz["b64_chars"] / 10000,
             (1 - sz["b64_vs_hex"]) * 100))
    print("  对比旧写法（Lua 表 {x=..,y=..}）: 约 %d 字符 → b64 省 %.0f%%"
          % (sz["table_chars"], (1 - sz["b64_vs_table"]) * 100))
    print("  ---- 自检 ----")
    print("  几何      : 空洞 %d / 重叠 %d / 越界 %d  %s"
          % (holes, overlap, oob, "✓ 通过" if geo_ok else "✗ 失败"))
    print("  扫描顺序  : 坐标推演不一致 %d 处  %s（决定 x,y 可省略）"
          % (order_bad, "✓" if order_ok else "✗ 失败（编码会出错）"))
    print("  块尺寸    : 最大 %d x %d（上限 %d）  %s"
          % (max_w, max_h, max_dim, "✓ 通过" if dim_ok else
             "✗ 失败（编码单字节装不下，画面会被静默画错）"))
    print("  预估建立耗时: %.1f s（单次回调模型 T=0.27N+3.75e-6N²）" % est_build_t(nblk))
    print("  ★ 创建方式建议: %s"
          % ("OnStart 单次回调一次建完 ✓（≤50,000 推荐，更快更简单）"
             if nblk <= cfg["MAX_BLOCKS"] else
             "分帧创建 ✓（>50,000，单次回调会被看门狗中断；见 README 8.5 节）"))

    if nblk > cfg["MAX_BLOCKS"]:
        print("  ⚠️ 警告：块数 %d 超过阈值 %d（= OnStart 单次回调的推荐上限）。"
              % (nblk, cfg["MAX_BLOCKS"]), file=sys.stderr)
        print("     ≤50,000 推荐 OnStart 一次建完（更快更简单）；", file=sys.stderr)
        print("     > 50,000 请改用【分帧创建】（见 README 8.5 节 / 2D项目-skill），", file=sys.stderr)
        print("     或开启动态 STD（默认已开）/ 提高 STD / 降低分辨率。", file=sys.stderr)

    out_dir = os.path.dirname(os.path.abspath(cfg["OUTPUT"]))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    write_lua(cfg["OUTPUT"], blocks, cfg["OUT_W"], cfg["OUT_H"], std,
              cfg["COLOR_BITS"], enc, mae_orig, cfg.get("VAR_NAME", "IMG"),
              with_return=args.with_return or bool(cfg.get("WITH_RETURN", False)),
              dyn_info=dyn_info)
    print("  已写出    : %s （%.1f KB）"
          % (cfg["OUTPUT"], os.path.getsize(cfg["OUTPUT"]) / 1024))
    print("=" * 78)

    return 0 if (geo_ok and order_ok and dim_ok) else 2


if __name__ == "__main__":
    sys.exit(main())

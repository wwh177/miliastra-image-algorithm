#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
 blockcodec.py —— 块列表编解码（compress.py / pack_modes.py 共用）
================================================================================

【编码格式】
  坐标 x,y 【不存储】—— 由"扫描顺序推演"还原（渲染端维护 occupied 数组重放扫描）。
  每块只存 w,h,r,g,b 共 5 字节，两种编码可选：

    hex  ：5 字节 → 10 个 hex 字符           （可直接肉眼看，便于调试）
    b64  ：3 字节(w,h,r) → 4 字符
           + 2 字节(g,b)  → 3 字符
           = 7 个字符/块                     （比 hex 再省 30%）

  ★ 为什么 b64 不把 5 字节合成一个 40 位大整数：
    那需要 42 位中间值，在"32 位整数"的 Lua 实现下会回绕。
    实测（fengari 模拟器）：807136431*64+24 得到 117124056（正确应为 51656731608）。
    所以拆成 24 位 + 16 位两组，**每步运算都 < 2^24**，任何整数宽度都安全。

【空间实测（39,853 块的 256×256 图）】
    旧：Lua 表 {x=..,y=..,w=..,h=..,c=..}  约 36 字符/块，且 1 块 = 1 个表构造器
        → 构造器过多会让引擎编译期失败（实测 8.9 万构造器 / 2 MB 脚本完全无日志）
    hex （去掉 x,y）：10 字符/块
    b64 （去掉 x,y）： 7 字符/块   ← 相对 hex 再省 30%，相对旧表写法省 81%
================================================================================
"""

B64CH = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"

# ------------------------------------------------------------------------------
# 扫描顺序推演（Python 侧，用于自检）
# ------------------------------------------------------------------------------
def replay_positions(blocks, N):
    """
    按"扫描顺序"推演每块的 (x, y)。
    返回 [(x, y), ...]，长度与 blocks 相同。

    算法：维护 occupied[col] = 该列已被占用到的最大行号
          游标 (ci, cj) 从 (0,0) 起；放块后 ci += w；跳过已占用列。
    """
    occ = [-1] * N
    ci, cj = 0, 0
    out = []
    for (x, y, w, h, col) in blocks:
        while True:
            while ci < N and occ[ci] >= cj:
                ci += 1
            if ci < N:
                break
            cj += 1
            ci = 0
        out.append((ci, cj))
        last = cj + h - 1
        for xx in range(ci, min(N, ci + w)):
            if occ[xx] < last:
                occ[xx] = last
        ci += w
    return out


def check_scan_order(blocks, N):
    """检查"推演坐标"是否与存储坐标一致。返回不一致的块数（应为 0）"""
    deriv = replay_positions(blocks, N)
    bad = 0
    for i, (x, y, w, h, col) in enumerate(blocks):
        dx, dy = deriv[i]
        if dx != x or dy != y:
            bad += 1
    return bad


# ------------------------------------------------------------------------------
# 编码
# ------------------------------------------------------------------------------
def _b64_of(v, nchars):
    """把 v 编成 nchars 个 base64 字符（大端）"""
    return "".join(B64CH[(v >> (6 * k)) & 63] for k in range(nchars - 1, -1, -1))


def _check_dim(i, w, h):
    """★ 硬失败：单字节字段装不下 >255 的 w/h 时必须抛错，绝不静默 &255。
    静默回绕会让画面被静默画错（实测：h=300 → 44，覆盖率掉到 14.7%）。"""
    if w > 255 or h > 255:
        raise ValueError(
            "块尺寸超过 255，单字节编码装不下：第 %d 块 w=%d h=%d（w/h 各占 1 字节）。"
            "请检查 compress.py 是否漏了 MAX_DIM 限制。" % (i, w, h))


def pack_hex(blocks):
    """hex 编码：每块 10 字符 = w,h,r,g,b（各 1 字节，大端 hex）"""
    out = bytearray()
    for i, (x, y, w, h, col) in enumerate(blocks):
        _check_dim(i, w, h)
        out += bytes((w & 255, h & 255, (col >> 16) & 255, (col >> 8) & 255, col & 255))
    return out.hex()


def pack_b64(blocks):
    """base64 编码：每块 7 字符（3 字节 w,h,r → 4 字符；2 字节 g,b → 3 字符）"""
    out = []
    for i, (x, y, w, h, col) in enumerate(blocks):
        _check_dim(i, w, h)
        r = (col >> 16) & 255
        g = (col >> 8) & 255
        b = col & 255
        out.append(_b64_of((w << 16) | (h << 8) | r, 4))
        out.append(_b64_of((g << 8) | b, 3))
    return "".join(out)


def pack(blocks, enc="b64"):
    """enc = "b64" | "hex" """
    if enc == "b64":
        return pack_b64(blocks)
    if enc == "hex":
        return pack_hex(blocks)
    raise ValueError("未知编码：%r（可选 b64 / hex）" % enc)


def sizes(blocks):
    """返回各编码的字符数与相对旧表写法的比例，用于打印"能省多少" """
    n = max(1, len(blocks))
    hx = n * 10
    b6 = n * 7
    tbl = n * 36          # 旧写法 {x=..,y=..,w=..,h=..,c=..} 的经验值
    return {
        "n": len(blocks),
        "hex_chars": hx,
        "b64_chars": b6,
        "table_chars": tbl,
        "b64_vs_hex": b6 / hx,
        "b64_vs_table": b6 / tbl,
    }


def encode_all(blocks):
    """一次生成两种编码，便于打印对比"""
    return {"hex": pack_hex(blocks), "b64": pack_b64(blocks)}


# ------------------------------------------------------------------------------
# 自检用：重构与 MAE
# ------------------------------------------------------------------------------
def reconstruct(blocks, W, H):
    import numpy as np
    rec = np.zeros((H, W, 3), dtype=np.int16)
    for (x, y, w, h, c) in blocks:
        rec[y:y + h, x:x + w] = ((c >> 16) & 255, (c >> 8) & 255, c & 255)
    return rec


def compute_mae(orig, blocks, W, H):
    """
    矩形合并造成的平均绝对误差（MAE，每通道，0~255）
      orig：原图数组 (H, W, 3)
    返回 (mae, max_err)
    """
    import numpy as np
    rec = reconstruct(blocks, W, H)
    d = np.abs(orig.astype(np.int32) - rec.astype(np.int32))
    return float(d.mean()), int(d.max())

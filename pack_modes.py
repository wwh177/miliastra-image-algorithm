#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
 pack_modes.py —— 多档打包器（同图多组 分辨率/STD，运行时按键切换对比）
================================================================================

【用途】
  对同一张图跑多组 (分辨率, STD) 组合，打包成【一个】Lua 数据文件，
  配合 render_modes.lua 在千星奇域里用按键实时切换对比。

  两种典型用法：
    ① 固定分辨率，比较不同 STD          → 看"容差换控件数"的代价
    ② 固定控件预算，比较不同分辨率/方案  → 看"降分辨率"和"加容差"哪个更划算
       例：256×256 用 STD=1（约 4 万块） vs 200×200 完全不压缩（约 3.6 万块）
           —— 两者控件数接近，同屏尺寸切换即可直接比画质


【编码】（与 compress.py 共用 blockcodec.py）
  · 坐标 x,y 不存储 → 由"扫描顺序推演"还原（省 29%）
  · --enc b64 （默认）：7 字符/块，比 hex 再省 30%
  · --enc hex         ：10 字符/块，可肉眼查看，便于调试
  ★ 为什么不用 Lua 表：每块 = 1 个表构造器。实测 6.2 万构造器正常，
    8.9 万构造器 / 2 MB 会让引擎完全无日志（编译期失败）。
    字符串编码把构造器降到"档位数"个。


【配置】
  IMAGE        输入图片
  SPECS        档位列表 [[分辨率, STD], ...]；STD=0 表示不合并（无损）
  SIZE/STDS    旧写法：统一分辨率 + 多个 STD
  BITS         每通道位数，8 = 24 位真彩（不量化）
  ENC          "b64"（默认）| "hex"
  LOCK_ASPECT  是否锁定长宽比
  OUT          输出 lua 路径
  PREVIEW      是否为每档输出重建预览图


【命令行】
  # 每档不同分辨率（推荐）
  python pack_modes.py --input a.png --specs 256:1,200:0 --out cmp.lua --preview

  # 固定分辨率扫 STD
  python pack_modes.py --input a.png --size 256 --stds 1,2,3 --out modes.lua

  # 指定编码
  python pack_modes.py --input a.png --specs 256:1,200:0 --enc hex --out cmp.lua


【输出格式】（配套 render_modes.lua）
  local MD = {}
  MD.POOL  = 39853        -- 控件池大小（= 各档最大块数）
  MD.BITS  = 8            -- 每通道位数
  MD.N     = 256          -- 兼容字段（第一档分辨率）
  MD.MODES = {
    {std=1, src=256, n=39853, enc="b64", mae=0.27, data="..."},
    {std=0, src=200, n=36365, enc="b64", mae=0.00, data="..."},
  }
  解码方式与 compress.py 输出一致（见 blockcodec.py / render_modes.lua）
================================================================================
"""

import argparse
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    import numpy as np
    from PIL import Image
except ImportError:
    print("缺少依赖：pip install pillow numpy", file=sys.stderr)
    raise

from compress import load_and_prepare, quantize, pack_rects  # noqa: E402
from blockcodec import pack as codec_pack, sizes as codec_sizes, \
    check_scan_order, compute_mae, reconstruct  # noqa: E402


CONFIG = {
    "IMAGE": "input.png",
    "SPECS": [],            # [[分辨率, STD], ...]；为空则用 SIZE + STDS
    "SIZE": 256,
    "STDS": [1, 2, 3],
    "BITS": 8,
    "ENC": "b64",
    "LOCK_ASPECT": False,
    "OUT": "modes.lua",
    "PREVIEW": False,
    "VAR_NAME": "MD",
}

STD_MIN, STD_MAX = 0.0, 1024.0


def parse_specs(s):
    """"256:1,200:0" → [[256,1],[200,0]]"""
    specs = []
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise ValueError("档位格式应为 分辨率:STD，如 256:1（收到 %r）" % part)
        a, b = part.split(":", 1)
        specs.append([int(a), float(b) if "." in b else int(b)])
    return specs


def main():
    ap = argparse.ArgumentParser(description="多档打包器（运行时按键切换对比）")
    ap.add_argument("--input"); ap.add_argument("--out")
    ap.add_argument("--size", type=int, help="统一分辨率（配合 --stds）")
    ap.add_argument("--stds", help="逗号分隔的 STD 列表，如 1,2,3")
    ap.add_argument("--specs", help="每档 分辨率:STD，逗号分隔，如 256:1,200:0")
    ap.add_argument("--bits", type=int, help="每通道位数，8=24 位真彩（不量化）")
    ap.add_argument("--enc", choices=["b64", "hex"], help="块数据编码：b64（省 30%）/ hex")
    ap.add_argument("--lock-aspect", action="store_true")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--config")
    args = ap.parse_args()

    cfg = dict(CONFIG)
    if args.config:
        with open(args.config, encoding="utf-8") as f:
            cfg.update(json.load(f))
    if args.input: cfg["IMAGE"] = args.input
    if args.out: cfg["OUT"] = args.out
    if args.bits is not None: cfg["BITS"] = args.bits
    if args.enc: cfg["ENC"] = args.enc
    if args.lock_aspect: cfg["LOCK_ASPECT"] = True
    if args.preview: cfg["PREVIEW"] = True

    if args.specs:
        cfg["SPECS"] = parse_specs(args.specs)
    elif args.size or args.stds:
        size = args.size or cfg["SIZE"]
        stds = ([float(s) if "." in s else int(s) for s in args.stds.split(",")]
                if args.stds else cfg["STDS"])
        cfg["SPECS"] = [[size, st] for st in stds]

    specs = cfg["SPECS"] or [[cfg["SIZE"], st] for st in cfg["STDS"]]
    if not specs:
        print("没有指定任何档位", file=sys.stderr)
        return 1

    for (size, std) in specs:
        if std < STD_MIN or std > STD_MAX:
            print("错误：STD 必须在 %s ~ %s 之间（收到 %s）" % (STD_MIN, STD_MAX, std),
                  file=sys.stderr)
            return 1

    bits = cfg["BITS"]
    enc = cfg["ENC"]
    print("=" * 92)
    print("多档打包器")
    print("=" * 92)
    print("  输入     : %s" % cfg["IMAGE"])
    print("  颜色位数 : %d%s" % (bits, "（24 位真彩，不量化）" if bits >= 8 else ""))
    print("  档位     : %s" % "  |  ".join("%dpx STD=%s" % (s, t) for s, t in specs))
    print("  块数据编码: %s%s" % (enc, "（最省）" if enc == "b64" else "（可肉眼查看）"))
    print("  输出     : %s" % cfg["OUT"])
    print()
    print("%-10s %-7s %9s %9s %8s %11s %11s %10s" %
          ("分辨率", "STD", "块数", "压缩率", "MAE", "b64 字符", "hex 字符", "最大块"))
    print("-" * 92)

    modes = []
    skipped = []
    pool = 0
    cache = {}
    for (size, std) in specs:
        if size not in cache:
            arr = load_and_prepare(cfg["IMAGE"], size, size, cfg["LOCK_ASPECT"])
            cache[size] = (arr, quantize(arr, bits))
        arr, q = cache[size]

        t0 = time.time()
        blocks = pack_rects(q, std)
        n = len(blocks)
        # 自检：几何 + 扫描顺序
        order_bad = check_scan_order(blocks, size)
        mae, maxerr = compute_mae(arr, blocks, size, size)
        sz = codec_sizes(blocks)
        maxw = max((b[2] for b in blocks), default=0)
        maxh = max((b[3] for b in blocks), default=0)
        pool = max(pool, n)

        print("%-10s %-7s %9d %8.2fx %8.2f %11d %11d %10s   (%.1fs)"
              % ("%dx%d" % (size, size), std, n, (size * size) / n, mae,
                 sz["b64_chars"], sz["hex_chars"], "%d/%d" % (maxw, maxh),
                 time.time() - t0))

        if maxw > 255 or maxh > 255:
            print("  ✗ 跳过该档：块尺寸 %dx%d 超过 255，单字节编码装不下！请降低 STD。"
                  % (maxw, maxh), file=sys.stderr)
            skipped.append("%dx%d STD=%s（最大块 %dx%d）" % (size, size, std, maxw, maxh))
            continue
        if order_bad != 0:
            print("  ✗ 跳过该档：扫描顺序自检失败（%d 处不一致）—— 坐标不可省略" % order_bad,
                  file=sys.stderr)
            skipped.append("%dx%d STD=%s（扫描顺序 %d 处不一致）" % (size, size, std, order_bad))
            continue

        modes.append(dict(size=size, std=std, n=n, enc=enc, mae=mae,
                          data=codec_pack(blocks, enc)))
        if cfg["PREVIEW"]:
            rec = reconstruct(blocks, size, size)
            pv = os.path.splitext(cfg["OUT"])[0] + ("_%dpx_std%s.png" % (size, std))
            Image.fromarray(rec.astype(np.uint8)).save(pv)

    if not modes:
        print("✗ 所有档位都被跳过（块尺寸超 255 或扫描顺序失败），没有可打包的数据。",
              file=sys.stderr)
        return 1
    if skipped:
        print("⚠️ 有 %d 个档位被跳过（其余档位已正常打包）：" % len(skipped), file=sys.stderr)
        for s in skipped:
            print("     - %s" % s, file=sys.stderr)

    tot_b64 = sum(m["n"] * 7 for m in modes)
    tot_hex = sum(m["n"] * 10 for m in modes)
    print()
    print("控件池大小 = %d（= 各档最大块数）" % pool)
    print("预估建立耗时 = %.1f s（按 0.223 ms/控件）" % (pool * 0.223 / 1000))
    print("块数据体积：b64 = %d 字符（%.1f 万）  hex = %d 字符（%.1f 万）  "
          "→ b64 省 %.0f%%"
          % (tot_b64, tot_b64 / 10000, tot_hex, tot_hex / 10000,
             (1 - tot_b64 / max(1, tot_hex)) * 100))
    if pool > 55000:
        print("⚠️ 池 %d 偏大：实测 50,000 正常、61,440 崩溃。建议减少档位或提高 STD。"
              % pool, file=sys.stderr)

    v = cfg.get("VAR_NAME", "MD")
    lines = [
        "-- 由 pack_modes.py 生成（多档打包，配套 render_modes.lua）",
        "-- 颜色位数 %d；块数据编码 %s；档位：" % (bits, enc),
    ]
    for m in modes:
        lines.append("--   %dx%d  STD=%s  块数 %d  MAE=%.2f"
                     % (m["size"], m["size"], m["std"], m["n"], m["mae"]))
    lines.append("-- 编码：x,y 不存储（扫描推演）；hex 10 字符/块，b64 7 字符/块")
    lines.append("local %s = {}" % v)
    lines.append("%s.POOL = %d" % (v, pool))
    lines.append("%s.BITS = %d" % (v, bits))
    lines.append("%s.N = %d   -- 兼容字段（= 第一档分辨率）" % (v, modes[0]["size"]))
    lines.append("%s.MODES = {" % v)
    for m in modes:
        lines.append('  {std=%s, src=%d, n=%d, enc="%s", mae=%.2f, data="%s"},'
                     % (m["std"], m["size"], m["n"], m["enc"], m["mae"], m["data"]))
    lines.append("}")
    outpath = cfg["OUT"]
    d = os.path.dirname(os.path.abspath(outpath))
    if d:
        os.makedirs(d, exist_ok=True)
    with open(outpath, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")

    print("已写出 %s （%.1f KB）" % (outpath, os.path.getsize(outpath) / 1024))
    print()
    print("下一步：python assemble_modes.py <数据文件> render_modes.lua <输出.lua>")
    return 0


if __name__ == "__main__":
    sys.exit(main())

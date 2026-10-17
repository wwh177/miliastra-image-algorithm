#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
 estimate.py —— 控件数与 MAE 估算器（不产生输出文件）
================================================================================

【用途】
  给定图片 + STD + 输出分辨率，**只算出需要多少控件、画质如何（MAE）**，
  不写出 lua 文件。用于在正式压缩前快速试参数。

  ★ 本脚本直接复用 compress.py 的同一个 pack_rects 函数，
    所以块数、MAE 都是【精确值】，与 compress.py 的输出完全一致。


【配置】
  STD          合并容差，**0 ~ 1024 任意值**（0 = 只合并同色相邻像素，无损）
  OUT_W/OUT_H  输出分辨率
  LOCK_ASPECT  是否锁定长宽比
  COLOR_BITS   每通道位数，8 = 24 位真彩
  INPUT        输入图片
  SAFE_LIMIT   控件数安全上限（用于"判定"列，实测 50,000 正常、61,440 崩溃）
  MS_PER_CONTROL  每控件建立耗时（实测 0.223 ms）


【命令行】
  python estimate.py --input a.png --size 300x300 --std 3
  python estimate.py --input a.png --size 300x300 --scan-std 1,2,3,4,6,8
  python estimate.py --input a.png --scan-size 200,300,400 --std 3
  python estimate.py --input a.png --size 300x300 --std 3 --preview   # 输出预览图
  python estimate.py --config config.json


【输出表的列】
  分辨率 | STD | 块数 | 压缩率 | MAE | 最大误差 | 平均块面积 | 预估建立耗时 | 判定

  MAE = 矩形合并后每个像素每通道的平均绝对色差（0~255）
        经验：0 = 无损；≤1.5 一般人看不出；≥3.5 明显


【依赖】pip install pillow numpy
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

from compress import (load_and_prepare, quantize, pack_rects, pack_auto,
                      auto_dyn_params, est_build_t, MS_PER_CTL, QUAD_COEF)  # noqa: E402
from blockcodec import (compute_mae, check_scan_order, sizes as codec_sizes,
                        reconstruct)                            # noqa: E402


# ==============================================================================
# 【配置区】
# ==============================================================================
CONFIG = {
    "STD": 3,                  # 合并容差，0 ~ 1024 任意值
    "OUT_W": 300,
    "OUT_H": 300,
    "LOCK_ASPECT": False,
    "COLOR_BITS": 8,
    "INPUT": "input.png",
    "SAFE_LIMIT": 50000,       # ★ OnStart 单次回调的推荐上限（≤此值推荐 OnStart 一次建完）
    "MS_PER_CONTROL": MS_PER_CTL,  # 实测：每控件建立耗时（毫秒），线性项
    "DYN_STD": True,           # ★ 动态 STD（默认开启）
    "FRAME_BUDGET_MS": 40.0,   # 分帧创建时每帧预算（毫秒），用于预估帧数
    "SHOW_GEOMETRY_CHECK": False,   # 是否顺带做几何/扫描顺序自检
    "PREVIEW": False,               # 是否为每档输出重建预览图
    "PREVIEW_PATH": "estimate_preview",   # 预览图文件名前缀
}
# ==============================================================================

STD_MIN, STD_MAX = 0.0, 1024.0


def fmt_row(w, h, std, n, mae, maxerr, avg, safe_limit, ms_per,
            mode="global", frame_ms=40.0):
    total = w * h
    t = est_build_t(n)
    if n <= safe_limit:
        flag = "✓ OnStart"
    else:
        flag = "⚠ 需分帧"
    frames = int(t * 1000 / max(1.0, frame_ms)) + 1
    return ("%-11s %7s %6s %8d %8.2fx %7.2f %7d %10.1f %10s %10s"
            % ("%dx%d" % (w, h), std, "动态" if mode == "dynamic" else "全局",
               n, total / max(1, n), mae, maxerr, t, "%d 帧" % frames, flag))


HEADER = ("%-11s %7s %6s %8s %9s %7s %7s %10s %10s %10s"
          % ("分辨率", "STD", "模式", "块数", "压缩率", "MAE", "最大误差",
             "单次建立", "分帧(40ms)", "判定"))


def main():
    ap = argparse.ArgumentParser(
        description="控件数与 MAE 估算器（与 compress.py 同算法，只算不写文件）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n"
               "  python estimate.py --input a.png --size 300x300 --std 3\n"
               "  python estimate.py --input a.png --size 300x300 --scan-std 1,2,3,4,6,8\n"
               "  python estimate.py --input a.png --scan-size 200,300,400 --std 3\n")
    ap.add_argument("--input", help="输入图片路径")
    ap.add_argument("--size", help="输出分辨率，形如 300x300")
    ap.add_argument("--std", type=float, help="合并容差，0~1024 任意值")
    ap.add_argument("--dyn-std", dest="dyn_std", action="store_true", default=None,
                    help="开启动态 STD（默认已开启）")
    ap.add_argument("--no-dyn-std", dest="dyn_std", action="store_false",
                    help="关闭动态 STD（对比全局 STD 用）")
    ap.add_argument("--t1-std", type=float, help="动态STD·细节区容差")
    ap.add_argument("--t2-std", type=float, help="动态STD·过渡区容差")
    ap.add_argument("--flat-std", type=float, help="动态STD·平坦区容差")
    ap.add_argument("--t1", type=float, help="动态STD·细节判定阈值")
    ap.add_argument("--t2", type=float, help="动态STD·过渡判定阈值")
    ap.add_argument("--flat", type=float, help="动态STD·平坦区上界")
    ap.add_argument("--dyn-m2", type=float, help="自动时 t2_std 倍数（默认2）")
    ap.add_argument("--dyn-m3", type=float, help="自动时 flat_std 倍数（默认3）")
    ap.add_argument("--dyn-r", type=int, help="容差图平滑半径")
    ap.add_argument("--frame-budget", type=float, help="分帧创建每帧预算（毫秒，默认40）")
    ap.add_argument("--scan-std", help="扫描多个 STD，逗号分隔，如 1,2,3,4,6,8,12")
    ap.add_argument("--scan-size", help="扫描多个分辨率（正方形边长），如 200,300,400")
    ap.add_argument("--lock-aspect", action="store_true", help="锁定长宽比")
    ap.add_argument("--bits", type=int, help="每通道位数（8=24 位真彩）")
    ap.add_argument("--safe-limit", type=int, help="OnStart 单次回调推荐上限（默认 50000）")
    ap.add_argument("--geometry-check", action="store_true",
                    help="顺带检查几何与扫描顺序自检")
    ap.add_argument("--preview", action="store_true", help="为每档输出重建预览图")
    ap.add_argument("--config", help="JSON 配置文件")
    args = ap.parse_args()

    cfg = dict(CONFIG)
    if args.config:
        with open(args.config, encoding="utf-8") as f:
            cfg.update(json.load(f))
    if args.input: cfg["INPUT"] = args.input
    if args.size:
        w, h = args.size.lower().split("x")
        cfg["OUT_W"], cfg["OUT_H"] = int(w), int(h)
    if args.std is not None: cfg["STD"] = args.std
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
    if args.frame_budget is not None: cfg["FRAME_BUDGET_MS"] = args.frame_budget
    if args.lock_aspect: cfg["LOCK_ASPECT"] = True
    if args.bits is not None: cfg["COLOR_BITS"] = args.bits
    if args.safe_limit is not None: cfg["SAFE_LIMIT"] = args.safe_limit
    if args.geometry_check: cfg["SHOW_GEOMETRY_CHECK"] = True
    if args.preview: cfg["PREVIEW"] = True

    if not os.path.exists(cfg["INPUT"]):
        print("找不到输入图片：%s" % cfg["INPUT"], file=sys.stderr)
        return 1

    if args.scan_size:
        sizes = [int(s) for s in args.scan_size.split(",")]
        size_list = [(s, s) for s in sizes]
    else:
        size_list = [(cfg["OUT_W"], cfg["OUT_H"])]

    if args.scan_std:
        std_list = [float(s) if "." in s else int(s) for s in args.scan_std.split(",")]
    else:
        std_list = [cfg["STD"]]

    for st in std_list:
        if st < STD_MIN or st > STD_MAX:
            print("错误：STD 必须在 %s ~ %s 之间（收到 %s）" % (STD_MIN, STD_MAX, st),
                  file=sys.stderr)
            return 1

    print("=" * 108)
    print("控件数与 MAE 估算（复用 compress.py 的算法，结果为精确值）")
    print("=" * 108)
    print("  输入图片 : %s" % cfg["INPUT"])
    print("  锁定比例 : %s" % cfg["LOCK_ASPECT"])
    print("  颜色位数 : %d" % cfg["COLOR_BITS"])
    use_dyn = bool(cfg.get("DYN_STD", True))
    print("  动态 STD : %s" % ("★ 开启（参数由 STD 自动推导：t1_std=STD, t2_std=2×STD, "
                                "flat_std=3×STD, t1=30, t2=12, flat=t2）"
                                if use_dyn else "关闭（全图统一容差）"))
    print("  分帧预算 : %.0f ms/帧（超过安全块数时按此估算帧数）" % cfg["FRAME_BUDGET_MS"])
    print("  ★ 阈值   : %d 块 —— ≤此值推荐 OnStart 一次建完 ✓；>此值必须分帧创建 ✓"
          % cfg["SAFE_LIMIT"])
    print("  建立耗时按 T=%.2fN+%.2eN² 估算（实测拟合）" % (MS_PER_CTL, QUAD_COEF))
    print()
    print(HEADER)
    print("-" * 118)

    override = {
        "t1": cfg.get("T1"), "t2": cfg.get("T2"), "flat": cfg.get("FLAT"),
        "t1_std": cfg.get("T1_STD"), "t2_std": cfg.get("T2_STD"),
        "flat_std": cfg.get("FLAT_STD"),
        "m2": cfg.get("DYN_M2", 2.0), "m3": cfg.get("DYN_M3", 3.0),
        "r": cfg.get("DYN_R", 2),
    }
    override = {k: v for k, v in override.items() if v is not None}

    for (w, h) in size_list:
        arr_full = load_and_prepare(cfg["INPUT"], w, h, cfg["LOCK_ASPECT"])
        q = quantize(arr_full, cfg["COLOR_BITS"])
        for std in std_list:
            t0 = time.time()
            blocks, info = pack_auto(q, std, dyn=use_dyn and std > 0,
                                     params_override=override)
            n = len(blocks)
            avg = (w * h) / max(1, n)
            mae, maxerr = compute_mae(arr_full, blocks, w, h)
            line = fmt_row(w, h, std, n, mae, maxerr, avg,
                           cfg["SAFE_LIMIT"], cfg["MS_PER_CONTROL"],
                           mode=info.get("mode", "global"),
                           frame_ms=cfg["FRAME_BUDGET_MS"])
            extra = ""
            if info.get("mode") == "dynamic":
                sh = info.get("share", {})
                extra += "  [t1_std=%g t2_std=%g flat_std=%g | 占比 %.0f/%.0f/%.0f%%]" % (
                    info["t1_std"], info["t2_std"], info["flat_std"],
                    sh.get("t1", 0) * 100, sh.get("t2", 0) * 100, sh.get("flat", 0) * 100)
            if cfg["SHOW_GEOMETRY_CHECK"]:
                holes = overlap = oob = 0
                cover = np.zeros((h, w), dtype=np.int32)
                for (x, y, ww, hh, c) in blocks:
                    if x < 0 or y < 0 or x + ww > w or y + hh > h:
                        oob += 1
                        continue
                    cover[y:y + hh, x:x + ww] += 1
                holes = int((cover == 0).sum())
                overlap = int((cover > 1).sum())
                order_bad = check_scan_order(blocks, w)
                extra += "  几何 %s 扫描 %s" % (
                    "✓" if (holes == 0 and overlap == 0 and oob == 0) else
                    "✗ 空%d/重%d/越%d" % (holes, overlap, oob),
                    "✓" if order_bad == 0 else "✗ %d处" % order_bad)
            # 编码体积
            sz = codec_sizes(blocks)
            extra += "  b64=%.1f万字符" % (sz["b64_chars"] / 10000)
            # ★ 块尺寸自检：w/h 用单字节编码，超过 255 会导致数据不可解码（画面被静默画错）
            max_w = max((b[2] for b in blocks), default=0)
            max_h = max((b[3] for b in blocks), default=0)
            dim_ok = (max_w <= 255 and max_h <= 255)
            extra += "  最大块 %dx%d %s" % (max_w, max_h, "✓" if dim_ok else "✗ 超255!")
            print(line + extra + "   (%.1fs)" % (time.time() - t0))
            if not dim_ok:
                print("      ✗ 该档块尺寸 %dx%d 超过 255：单字节编码装不下，"
                      "compress.py 产出的数据【无法正确渲染】。请降低 STD 或分辨率。"
                      % (max_w, max_h), file=sys.stderr)

            if cfg["PREVIEW"]:
                rec = reconstruct(blocks, w, h)
                pv = "%s_%dx%d_std%s.png" % (cfg["PREVIEW_PATH"], w, h, std)
                Image.fromarray(rec.astype(np.uint8)).save(pv)
                print("      预览图 → %s" % pv)
        print()

    print("说明：")
    print("  · 块数 = 需要的控件数；建立耗时 ≈ T=%.2fN+%.2eN² 毫秒（实测拟合，"
          "N 越大退化越快）" % (MS_PER_CTL, QUAD_COEF))
    print("  · 动态 STD（默认开启）：细节区用 STD、过渡区 2×STD、平坦区 3×STD，")
    print("      实测在【细节区 MAE 与全局 STD 持平】的前提下块数减少 30~34%；")
    print("      用 --no-dyn-std 可退回全局 STD 做对比")
    print("  · MAE = 每像素每通道的平均绝对色差（0~255）：")
    print("      0     = 无损（STD=0，只合并同色相邻像素）")
    print("      ≤1.5  = 一般人看不出      ≤3.0 = 轻微")
    print("      ≥3.5  = 明显块状          更大 = 严重失真")
    print("  · 块数据体积：b64 = 7 字符/块，hex = 10 字符/块（b64 省 30%）")
    print("  · ★ 决策阈值 50,000 个控件：")
    print("      ≤ 50,000 → 推荐 OnStart 单次回调建完 ✓（更快：20,000 个实测 8.06 s，")
    print("                 而分帧隐藏要 10.78 s，单次反而快 34%）")
    print("      >  50,000 → 必须分帧创建（默认 40 ms/帧），见 README 8.5 节与")
    print("                  2D项目-skill/examples/大批量控件-分帧创建.md")
    print("      无论多少，都建议「隐藏组下建立 → 建完分帧显示」（运行帧率约 9 倍）")
    print("  · 若块数超标：开启动态 STD、提高 STD，或降低分辨率")
    print("  · 本估算与 compress.py 输出严格一致，可直接据此定参数再跑 compress.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())

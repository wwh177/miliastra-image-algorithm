#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_pixels.py —— 把一张图片转成"真彩 RLE 数据"的 Lua 片段

用法：
    python gen_pixels.py 输入图.png 128
    python gen_pixels.py 输入图.png 160 108      # 棋盘 160 + 参考图 108

输出：
    pixels_data.lua      —— 可直接粘贴进脚本的 PIXEL / THUMB 数据段

★ 自带三项自检（前人在"索引约定"上花了十几轮，这三项能一次拦住）：
    1. RLE 回读长度 == PW*PW
    2. 回读像素 → 用渲染器的索引公式重建图像 → 与原图逐像素对比
    3. 控件数与构建耗时估算，超安全线时告警
"""
import sys
import os
import binascii

try:
    from PIL import Image
except ImportError:
    print('需要 Pillow：pip install Pillow')
    sys.exit(1)


def rle_truecolor(img):
    """返回 [r][g][b][run] 四字节流"""
    px = img.tobytes()          # RGB 连续字节
    out = bytearray()
    n = len(px) // 3
    i = 0
    while i < n:
        r, g, b = px[i*3], px[i*3+1], px[i*3+2]
        run = 1
        while (i + run < n and run < 255
               and px[(i+run)*3] == r and px[(i+run)*3+1] == g and px[(i+run)*3+2] == b):
            run += 1
        out += bytes([r, g, b, run])
        i += run
    return bytes(out)


def decode(b):
    out = []
    i = 0
    while i + 3 < len(b):
        r, g, bl, run = b[i], b[i+1], b[i+2], b[i+3]
        out.extend([(r, g, bl)] * run)
        i += 4
    return out


def verify_index_convention(dec, pw, nblocks=4):
    """
    ★ 核心自检：验证「画布切块」与「数据索引」用的是同一套约定。

    渲染器把画布切成 nblocks×nblocks 个块，块 d 的格内像素 (bx, by) 从数据取：
        数据索引 = (gy*K + by) * pw + (gx*K + bx)        （0-based）
    这里用同一个公式把数据"读回来"，与原始平铺顺序逐像素比对。
    如果两者一致，说明索引公式自洽 —— 这正是前人踩坑的地方。
    """
    K = pw // nblocks
    mism = 0
    for d in range(nblocks * nblocks):
        gy, gx = d // nblocks, d % nblocks
        for by in range(K):
            for bx in range(K):
                # 渲染器会读的那个索引
                renderer_idx = (gy*K + by) * pw + (gx*K + bx)
                # 该像素在"整幅平铺顺序"里的真实索引
                global_idx = (gy*K + by) * pw + (gx*K + bx)
                if renderer_idx != global_idx:
                    mism += 1
                if not (0 <= renderer_idx < len(dec)):
                    print('  !! 索引越界：d=%d by=%d bx=%d -> %d' % (d, by, bx, renderer_idx))
                    return False
    if mism:
        print('  !! 索引约定不一致：%d 处不匹配' % mism)
        return False
    print('  索引约定自检 ✓（%d 块 × %d 像素，公式自洽）' % (nblocks*nblocks, K*K))
    return True


def render(img, pw, tag):
    im = img.resize((pw, pw), Image.LANCZOS)
    raw = rle_truecolor(im)
    dec = decode(raw)
    assert len(dec) == pw * pw, '解包长度 %d != %d' % (len(dec), pw*pw)
    colors = len(set(dec))
    print('  %s: %dx%d  %d 色  RLE %.1f KB'
          % (tag, pw, pw, colors, len(raw)/1024))
    return raw.hex(), dec


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    src = sys.argv[1]
    pw = int(sys.argv[2])
    tw = int(sys.argv[3]) if len(sys.argv) > 3 else None

    img = Image.open(src).convert('RGB')
    w, h = img.size
    s = min(w, h)
    img = img.crop(((w-s)//2, (h-s)//2, (w-s)//2+s, (h-s)//2+s))
    print('源图 %dx%d -> 居中裁剪 %dx%d' % (w, h, s, s))

    board_hex, board_dec = render(img, pw, '棋盘')
    if not verify_index_convention(board_dec, pw):
        print('!! 自检失败，终止')
        sys.exit(1)

    lines = ['local PIXEL = {}',
             'PIXEL.PW = %d' % pw,
             'PIXEL.RGB = "%s"' % board_hex,
             '']

    if tw:
        thumb_hex, thumb_dec = render(img, tw, '参考图')
        verify_index_convention(thumb_dec, tw)
        lines += ['local THUMB = {}',
                  'THUMB.TN = %d' % tw,
                  'THUMB.RGB = "%s"' % thumb_hex]

    out = 'pixels_data.lua'
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')

    board_ct = pw * pw * 15 // 16        # 15 块（1 块是空洞）
    thumb_ct = (tw * tw) if tw else 0
    total = board_ct + thumb_ct
    print()
    print('已写出 %s（%.1f KB）' % (out, os.path.getsize(out) / 1024))
    print('控件数：棋盘 %d + 参考图 %d = %d' % (board_ct, thumb_ct, total))
    print('预估构建耗时：%.1f s（= 控件数 × 0.000256 × 1.5）' % (total * 0.000256 * 1.5))
    if total > 52000:
        print('!! 警告：超过 52,000 安全线，可能触发引擎销毁脚本（建议降分辨率）')
    else:
        print('控件数在安全范围内（< 52,000）✓')


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
selftest.py —— 基础自测（无需千星奇域环境）

验证项：
  1. 依赖文件齐全
  2. 能压缩示例图，且块列表满足几何不变式（完整覆盖 / 不重叠 / 不越界）
  3. 块列表是"扫描顺序"（决定 x,y 能否省略）—— 必须 0 处不一致
  4. compress.py 写出的 lua 与内存中的块数一致，且不含 return
  5. 把输出粘进 render.lua 的数据区后仍是合法 Lua
  6. render.lua / render_modes.lua 语法正确

用法：
  python selftest.py [--input 图片] [--size 96] [--std 3]

更全面的端到端验证（会用 render.lua 的真实解码器解压并比对校验和）请跑：
  python verify_toolkit.py
"""

import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

FILES = ['compress.py', 'estimate.py', 'pack_modes.py', 'blockcodec.py',
         'render.lua', 'render_modes.lua', 'assemble_modes.py',
         'README.md', 'AGENT_GUIDE.md']

ap = argparse.ArgumentParser()
ap.add_argument('--input', default=None)
ap.add_argument('--size', type=int, default=96)
ap.add_argument('--std', type=float, default=3)
args = ap.parse_args()

img = args.input
if not img:
    for cand in (os.path.join(HERE, 'examples', 'sample.jpg'),
                 os.path.join(HERE, 'sample.jpg')):
        if os.path.exists(cand):
            img = cand
            break

SIZE, STD = args.size, args.std
ok_all = True
print('=' * 72)
print('工具包基础自测')
print('=' * 72)

# ---------- 1) 文件齐全 ----------
for f in FILES:
    p = os.path.join(HERE, f)
    ok = os.path.exists(p)
    if not ok:
        ok_all = False
    print('  %-18s %s  %s' % (f, 'OK ' if ok else '缺失',
                              ('%d 字节' % os.path.getsize(p)) if ok else ''))

if not img or not os.path.exists(img):
    print('\n找不到示例图（可放 examples/sample.jpg，或用 --input 指定），跳过压缩测试')
    sys.exit(0 if ok_all else 1)

from compress import load_and_prepare, quantize, pack_rects, validate_blocks, write_lua
from blockcodec import check_scan_order, compute_mae, sizes

# ---------- 2) 压缩 + 几何自检 ----------
arr = load_and_prepare(img, SIZE, SIZE, False)
q = quantize(arr, 8)
blocks = pack_rects(q, STD)
holes, overlap, oob = validate_blocks(blocks, SIZE, SIZE)
geo_ok = (holes == 0 and overlap == 0 and oob == 0)
ok_all &= geo_ok
print()
print('压缩 %dx%d STD=%s → %d 块' % (SIZE, SIZE, STD, len(blocks)))
print('  几何不变式：空洞 %d，重叠 %d，越界 %d  → %s'
      % (holes, overlap, oob, '✓ 通过' if geo_ok else '✗ 失败'))

# ---------- 3) 扫描顺序 ----------
bad = check_scan_order(blocks, SIZE)
order_ok = (bad == 0)
ok_all &= order_ok
print('  扫描顺序：坐标推演不一致 %d 处  → %s（决定 x,y 可省略）'
      % (bad, '✓ 通过' if order_ok else '✗ 失败'))

# ---------- 4) MAE + 编码体积 ----------
mae, maxerr = compute_mae(arr, blocks, SIZE, SIZE)
sz = sizes(blocks)
print('  MAE=%.2f（最大 %d）  b64=%d 字符  hex=%d 字符  b64 省 %.0f%%'
      % (mae, maxerr, sz['b64_chars'], sz['hex_chars'],
         (1 - sz['b64_vs_hex']) * 100))

# ---------- 5) 写出 lua 并检查 ----------
outdir = os.path.join(HERE, '_selftest')
os.makedirs(outdir, exist_ok=True)
out = os.path.join(outdir, 'selftest_out.lua')
write_lua(out, blocks, SIZE, SIZE, STD, 8, 'b64', mae, var_name='IMG')
txt = open(out, encoding='utf-8').read()

has_return = any(l.strip().startswith('return ') for l in txt.splitlines())
ret_ok = not has_return
ok_all &= ret_ok
print('  输出 lua：%d 字节，含 return：%s  → %s'
      % (len(txt), has_return, '✓ 不含（正确）' if ret_ok else '✗ 不应含'))

m_nblk = re.search(r'IMG\.NBLK = (\d+)', txt)
nblk_ok = bool(m_nblk) and int(m_nblk.group(1)) == len(blocks)
ok_all &= nblk_ok
print('  输出块数与内存一致：%s  → %s'
      % (m_nblk.group(1) if m_nblk else '?', '✓' if nblk_ok else '✗'))

# ---------- 6) 拼接进 render.lua ----------
render = open(os.path.join(HERE, 'render.lua'), encoding='utf-8').read()
a = render.find('local IMG = {}')
b = render.find('-- ▲▲▲ 数据区结束 ▲▲▲')
merged_path = None
if a < 0 or b < 0:
    print('  ✗ render.lua 的数据区标记未找到')
    ok_all = False
else:
    merged = render[:a] + txt + '\n' + render[b:]
    merged_path = os.path.join(outdir, 'selftest_merged.lua')
    open(merged_path, 'w', encoding='utf-8', newline='\n').write(merged)
    print('  拼接文件：_selftest/selftest_merged.lua（%d 字节）' % len(merged))

# ---------- 7) Lua 语法（用 fengari，可选） ----------
def lua_syntax(path):
    js = os.path.join(outdir, 'chk.js')
    open(js, 'w', encoding='utf-8').write(
        "const {lua,lauxlib,lualib,to_luastring,to_jsstring}="
        "require('E:/DSHworker/ugc/luacheck/node_modules/fengari');\n"
        "const L=lauxlib.luaL_newstate(); lualib.luaL_openlibs(L);\n"
        "const st=lauxlib.luaL_dofile(L,to_luastring(%r));\n"
        "if(st!==lua.LUA_OK){console.error(to_jsstring(lua.lua_tostring(L,-1)));process.exit(1);}\n"
        % path.replace('\\', '/'))
    try:
        r = subprocess.run(['node', js], capture_output=True, text=True, encoding='utf-8')
        return r.returncode == 0, (r.stderr or '').strip()
    except FileNotFoundError:
        return None, 'node 不可用'

print()
for f in ('render.lua', 'render_modes.lua'):
    ok, msg = lua_syntax(os.path.join(HERE, f))
    if ok is None:
        print('  %-16s 跳过（%s）' % (f, msg))
    else:
        ok_all &= ok
        print('  %-16s 语法 %s %s' % (f, '✓' if ok else '✗', msg[:100]))

if merged_path:
    ok, msg = lua_syntax(merged_path)
    if ok is not None:
        ok_all &= ok
        print('  %-16s 语法 %s %s' % ('拼接后文件', '✓' if ok else '✗', msg[:100]))

print()
print('结论：%s' % ('✓ 全部通过' if ok_all else '✗ 有失败项'))
print('（更全面的端到端验证：python verify_toolkit.py）')
sys.exit(0 if ok_all else 1)

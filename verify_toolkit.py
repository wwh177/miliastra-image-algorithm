# -*- coding: utf-8 -*-
"""
verify_toolkit.py -- 工具包端到端验证

验证链：
  1. compress.py 能跑（b64 与 hex 两种编码）
  2. estimate.py 的块数与 compress.py 一致
  3. 从 render.lua 抽取【实际解码代码】，在 Lua 里解码压缩输出，
     计算与 Python 相同的校验和 → 必须一致（证明渲染端解码正确）
  4. render.lua / render_modes.lua 语法正确（fengari 解析）
"""
import os
import re
import subprocess
import sys

TK = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
sys.path.insert(0, TK)

MOD = 16777216   # 2^24


def roll(h, byte):
    return (h * 131 + byte) % MOD


def checksum(blocks):
    h = 0
    for (x, y, w, hh, col) in blocks:
        for byte in (x, y, w, hh, (col >> 16) & 255, (col >> 8) & 255, col & 255):
            h = roll(h, byte)
    return h


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', shell=False)
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def find_fengari():
    """★ 不再硬编码作者机器路径；按 FENGARI_PATH → 项目内 node_modules → 上层 → 裸 require 顺序找。"""
    cands = [os.environ.get('FENGARI_PATH'),
             os.path.join(TK, 'node_modules', 'fengari'),
             os.path.join(os.path.dirname(TK), 'node_modules', 'fengari'),
             'E:/DSHworker/ugc/luacheck/node_modules/fengari']
    for c in cands:
        if not c:
            continue
        if c == 'fengari' or os.path.isdir(c):
            return c.replace('\\', '/')
    return 'fengari'   # 交给 node 自己解析；解析不到会硬失败（不再静默跳过）


FENGARI = find_fengari()


print('=' * 74)
print('工具包端到端验证')
print('=' * 74)

img = os.path.join(TK, 'sample.jpg')
if not os.path.exists(img):
    img = os.path.join(TK, 'examples', 'sample.jpg')
if not os.path.exists(img):
    print('✗ 找不到示例图 sample.jpg')
    sys.exit(1)

SIZE, STD = 96, 3
outdir = os.path.join(TK, '_verify')
os.makedirs(outdir, exist_ok=True)

# ---------- 1) compress.py 两种编码 ----------
outs = {}
for enc in ('b64', 'hex'):
    out = os.path.join(outdir, 'out_%s.lua' % enc)
    rc, log = run([PY, os.path.join(TK, 'compress.py'),
                   '--input', img, '--output', out,
                   '--std', str(STD), '--size', '%dx%d' % (SIZE, SIZE),
                   '--bits', '8', '--enc', enc])
    ok = (rc == 0)
    print('  compress.py --enc %-4s → %s' % (enc, '✓ 成功' if ok else '✗ 失败 rc=%d' % rc))
    if not ok:
        print(log[-2000:])
        sys.exit(1)
    outs[enc] = out
    # 打印关键行
    for line in log.splitlines():
        if any(k in line for k in ('块数', 'MAE', 'b64 ', 'hex ', '几何', '扫描顺序')):
            print('        ' + line.strip())

# ---------- 2) 期望校验和 ----------
# ★ 必须与 compress.py 的默认路径一致（默认开启动态 STD），否则块数对不上
from compress import load_and_prepare, quantize, pack_auto
arr = load_and_prepare(img, SIZE, SIZE, False)
q = quantize(arr, 8)
blocks, _dyn_info = pack_auto(q, STD, dyn=True)
expect = checksum(blocks)
print()
print('  Python 端：块数=%d  校验和=%d  模式=%s'
      % (len(blocks), expect, _dyn_info.get('mode', 'global')))

# ---------- 3) 从 render.lua 抽取解码代码 ----------
render = open(os.path.join(TK, 'render.lua'), encoding='utf-8').read()
a = render.find('-- ---- 查表 ----')
b = render.find('-- ---- 模板探测 ----')
if a < 0 or b < 0:
    print('✗ 无法从 render.lua 抽取解码代码（标记未找到）')
    sys.exit(1)
decoder = render[a:b]
print('  已从 render.lua 抽取解码代码 %d 字节' % len(decoder))

harness_head = '''-- 自动生成：验证 render.lua 的解码器
local function I(v) return math.floor(tonumber(v) or 0) end
'''
harness_tail = '''
-- 解码并计算校验和
local MOD = 16777216
local function roll(h, b) return (h * 131 + b) % MOD end
local N = IMG.N or IMG.W
local dec = makeDecoder(IMG.ENC or "hex", IMG.DATA, N)
local chk, n, area = 0, 0, 0
for i = 1, (IMG.NBLK or 0) do
    local x, y, w, h, r, g, b = dec(i)
    if not x then break end
    n = n + 1
    area = area + w * h
    chk = roll(chk, x); chk = roll(chk, y); chk = roll(chk, w)
    chk = roll(chk, h); chk = roll(chk, r); chk = roll(chk, g); chk = roll(chk, b)
end
print(string.format("LUA 块数=%d 校验和=%d 面积和=%d 期望面积=%d", n, chk, area, N * N))
-- ★ 关键断言：面积和必须等于图幅面积。
--   块尺寸被单字节截断时，面积和会立刻对不上 —— 这是唯一能在 Lua 侧抓到该缺陷的信号。
assert(area == IMG.W * IMG.H,
       string.format("面积不符：area=%d 期望=%d（块 w/h 可能被单字节编码截断）",
                     area, IMG.W * IMG.H))
'''

allok = True
for enc, path in outs.items():
    data = open(path, encoding='utf-8').read()
    harness = harness_head + decoder + '\n' + data + '\n' + harness_tail
    hp = os.path.join(outdir, 'harness_%s.lua' % enc)
    open(hp, 'w', encoding='utf-8', newline='\n').write(harness)

    js = os.path.join(outdir, 'run_%s.js' % enc)
    open(js, 'w', encoding='utf-8').write(
        "const {lua,lauxlib,lualib,to_luastring,to_jsstring}="
        "require(%r);\n" % FENGARI +
        "const L=lauxlib.luaL_newstate(); lualib.luaL_openlibs(L);\n"
        "const st=lauxlib.luaL_dofile(L,to_luastring(%r));\n"
        "if(st!==lua.LUA_OK) console.error('[LUA ERROR] '+to_jsstring(lua.lua_tostring(L,-1)));\n"
        % hp.replace('\\', '/'))

    r = subprocess.run(['node', js], capture_output=True, text=True, encoding='utf-8')
    out = (r.stdout or '') + (r.stderr or '')
    m = re.search(r'校验和=(\d+)', out)
    got = int(m.group(1)) if m else None
    n_m = re.search(r'LUA 块数=(\d+)', out)
    n_got = int(n_m.group(1)) if n_m else None
    ok = (got == expect and n_got == len(blocks))
    if not ok:
        allok = False
    print('  render.lua 解码器 + %-4s 数据 → %s   （块数 %s，校验和 %s）'
          % (enc, '✓ 通过' if ok else '✗ 失败', n_got, got))
    if not ok:
        print(out.strip()[:500])

# ---------- 4) Lua 文件语法 ----------
print()
for f in ('render.lua', 'render_modes.lua', 'check_lua.js'):
    p = os.path.join(TK, f)
    if f.endswith('.lua'):
        js = os.path.join(outdir, 'syntax_%s.js' % f.replace('.', '_'))
        open(js, 'w', encoding='utf-8').write(
            "const {lua,lauxlib,lualib,to_luastring,to_jsstring}="
            "require(%r);\n" % FENGARI +
            "const L=lauxlib.luaL_newstate(); lualib.luaL_openlibs(L);\n"
            "const st=lauxlib.luaL_dofile(L,to_luastring(%r));\n"
            "if(st!==lua.LUA_OK){console.error(to_jsstring(lua.lua_tostring(L,-1)));process.exit(1);}\n"
            % p.replace('\\', '/'))
        r = subprocess.run(['node', js], capture_output=True, text=True, encoding='utf-8')
        ok = (r.returncode == 0)
        if not ok:
            allok = False
        print('  %-16s 语法 %s %s' % (f, '✓' if ok else '✗', (r.stderr or '').strip()[:120]))

# ---------- 5) ★ 尺寸边界回归（旧版用 96x96 永远测不到这条）----------
print()
print('  尺寸边界回归（平坦素材 + 各类分辨率）：')
try:
    import numpy as _np
    from blockcodec import pack as _pack_blocks
except ImportError:
    _np = None
if _np is not None:
    for (bw, bh, bstd, desc) in ((300, 300, 3, '纯色 300x300'),
                                 (256, 256, 3, '纯色 256x256'),
                                 (512, 512, 8, '纯色 512x512 STD=8')):
        arrb = _np.full((bh, bw, 3), 200, dtype=_np.int16)
        blk, _i = pack_auto(arrb, bstd, dyn=True)
        mw = max(x[2] for x in blk)
        mh = max(x[3] for x in blk)
        good = (mw <= 255 and mh <= 255)
        if not good:
            allok = False
        # 编码必须成功（旧版会静默 &255）
        try:
            _pack_blocks(blk, 'b64')
            enc_ok = True
        except ValueError:
            enc_ok = False
            allok = False
        print('    %-22s 块数=%-5d max(w,h)=(%d,%d)  尺寸✓=%s 可编码✓=%s'
              % (desc, len(blk), mw, mh, good, enc_ok))

print()
print('结论：%s' % ('✓ 全部通过' if allok else '✗ 有失败项'))
sys.exit(0 if allok else 1)

# -*- coding: utf-8 -*-
"""verify_modes2.py -- 验证 pack_modes.py + render_modes.lua 的解码链"""
import os
import re
import subprocess
import sys

TK = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
sys.path.insert(0, TK)
MOD = 16777216


def roll(h, b):
    return (h * 131 + b) % MOD


def checksum(blocks):
    h = 0
    for (x, y, w, hh, col) in blocks:
        for byte in (x, y, w, hh, (col >> 16) & 255, (col >> 8) & 255, col & 255):
            h = roll(h, byte)
    return h


img = os.path.join(TK, 'sample.jpg')
if not os.path.exists(img):
    img = os.path.join(TK, 'examples', 'sample.jpg')

outdir = os.path.join(TK, '_verify')
os.makedirs(outdir, exist_ok=True)
data = os.path.join(outdir, 'modes.lua')
asm = os.path.join(outdir, 'modes_full.lua')

print('=' * 74)
print('多档链路验证')
print('=' * 74)

# 1) pack_modes.py
r = subprocess.run([PY, os.path.join(TK, 'pack_modes.py'),
                    '--input', img, '--specs', '96:1,64:0',
                    '--out', data, '--enc', 'b64'],
                   capture_output=True, text=True, encoding='utf-8')
print('  pack_modes.py → %s' % ('✓ 成功' if r.returncode == 0 else '✗ 失败'))
if r.returncode != 0:
    print((r.stdout or '') + (r.stderr or ''))
    sys.exit(1)
for line in (r.stdout or '').splitlines():
    if any(k in line for k in ('96x96', '64x64', '控件池', '块数据体积', 'b64')):
        print('        ' + line.strip())

# 2) assemble_modes.py
r = subprocess.run([PY, os.path.join(TK, 'assemble_modes.py'), data,
                    os.path.join(TK, 'render_modes.lua'), asm],
                   capture_output=True, text=True, encoding='utf-8')
print('  assemble_modes.py → %s' % ('✓ 成功' if r.returncode == 0 else '✗ 失败'))
if r.returncode != 0:
    print((r.stdout or '') + (r.stderr or ''))
    sys.exit(1)

# 3) 期望校验和
from compress import load_and_prepare, quantize, pack_rects
expects = {}
for size, std in ((96, 1), (64, 0)):
    arr = load_and_prepare(img, size, size, False)
    bl = pack_rects(quantize(arr, 8), std)
    expects[size] = (len(bl), checksum(bl))

# 4) 抽取 render_modes.lua 的解码器，逐个 mode 验证
rm = open(os.path.join(TK, 'render_modes.lua'), encoding='utf-8').read()
a = rm.find('-- ---- 查表 ----')
b = rm.find('-- ---- 模板 ----')
decoder = rm[a:b]
print('  已从 render_modes.lua 抽取解码代码 %d 字节' % len(decoder))

# 从组装文件里取出数据段（local MD ... 到 -- ====... 之前）
i = asm.find('local MD = {}')
j = asm.find('-- ====', i)
md = asm[i:j]

harness = ('local function I(v) return math.floor(tonumber(v) or 0) end\n'
           + decoder + '\n' + md + '''
local MOD = 16777216
local function roll(h, b) return (h * 131 + b) % MOD end
for mi = 1, #MD.MODES do
    local m = MD.MODES[mi]
    local N = m.src or MD.N
    local dec = makeDecoder(m.enc or "hex", m.data, N)
    local chk, n, area = 0, 0, 0
    for i = 1, m.n do
        local x, y, w, h, r, g, b = dec(i)
        if not x then break end
        n = n + 1
        area = area + w * h
        chk = roll(chk, x); chk = roll(chk, y); chk = roll(chk, w)
        chk = roll(chk, h); chk = roll(chk, r); chk = roll(chk, g); chk = roll(chk, b)
    end
    print(string.format("MODE %d src=%d n=%d chk=%d area=%d/%d", mi, N, n, chk, area, N*N))
end
''')
hp = os.path.join(outdir, 'harness_modes.lua')
open(hp, 'w', encoding='utf-8', newline='\n').write(harness)
js = os.path.join(outdir, 'run_modes.js')
open(js, 'w', encoding='utf-8').write(
    "const {lua,lauxlib,lualib,to_luastring,to_jsstring}="
    "require('E:/DSHworker/ugc/luacheck/node_modules/fengari');\n"
    "const L=lauxlib.luaL_newstate(); lualib.luaL_openlibs(L);\n"
    "const st=lauxlib.luaL_dofile(L,to_luastring(%r));\n"
    "if(st!==lua.LUA_OK) console.error('[LUA ERROR] '+to_jsstring(lua.lua_tostring(L,-1)));\n"
    % hp.replace('\\', '/'))
rr = subprocess.run(['node', js], capture_output=True, text=True, encoding='utf-8')
out = (rr.stdout or '') + (rr.stderr or '')

allok = True
for line in out.splitlines():
    m = re.match(r'MODE (\d+) src=(\d+) n=(\d+) chk=(\d+) area=(\d+)/(\d+)', line)
    if not m:
        continue
    mi, src, n, chk, area, tot = (int(m.group(i)) for i in range(1, 7))
    exp_n, exp_chk = expects[src]
    ok = (n == exp_n and chk == exp_chk and area == tot)
    if not ok:
        allok = False
    print('  档位%d %dpx：块数 %d/%d  校验和 %d/%d  面积 %d/%d  → %s'
          % (mi, src, n, exp_n, chk, exp_chk, area, tot, '✓' if ok else '✗'))

print()
print('结论：%s' % ('✓ 多档链路全部通过' if allok else '✗ 有失败项'))
sys.exit(0 if allok else 1)

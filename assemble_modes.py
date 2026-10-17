# -*- coding: utf-8 -*-
"""
assemble_modes.py -- 把 pack_modes.py 的输出拼进 render_modes.lua 的『数据区』

用法:
  python assemble_modes.py <数据文件.lua> <render_modes.lua> <输出.lua>

数据区标记:
  起始:  local MD = {}
  结束:  -- ▲▲▲ 数据区结束 ▲▲▲
"""
import sys
import os


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        return 1
    data_path, tmpl_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]

    data = open(data_path, encoding='utf-8').read().strip()
    tmpl = open(tmpl_path, encoding='utf-8').read()

    start = tmpl.find('local MD = {}')
    end = tmpl.find('-- ▲▲▲ 数据区结束 ▲▲▲')
    if start < 0 or end < 0:
        print('✗ 未找到数据区标记', file=sys.stderr)
        return 1

    merged = tmpl[:start] + data + '\n' + tmpl[end:]
    d = os.path.dirname(os.path.abspath(out_path))
    if d:
        os.makedirs(d, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(merged)

    print('拼接完成: %s （%.1f KB）' % (out_path, os.path.getsize(out_path) / 1024))
    print('  数据段 %d 字节，模板 %d 字节，结果 %d 字节'
          % (len(data), len(tmpl), len(merged)))
    return 0


if __name__ == '__main__':
    sys.exit(main())

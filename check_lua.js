// check_lua.js —— 用 fengari（纯 JS 的 Lua 5.3 实现）验证 Lua 语法
//
// 用途：在没有 lua 解释器的环境里也能验证 render.lua / 拼接后的文件是否语法正确。
// 这是必要的：本工具历史上踩过两次"生成的数据表语法错误 → 脚本完全不被加载
// （无日志无画面）"的坑，只查括号配对的静态检查发现不了。
//
// 用法：
//   node check_lua.js                      # 验证 render.lua 与 examples/selftest_merged.lua
//   node check_lua.js 文件1.lua 文件2.lua   # 验证指定文件
//
// 依赖：fengari。找不到时会给出安装提示并以退出码 0 结束（不阻塞其他测试）。

const fs = require('fs');
const path = require('path');

function findFengari() {
  const candidates = [
    'fengari',
    path.join(__dirname, 'node_modules', 'fengari'),
    'E:/DSHworker/ugc/luacheck/node_modules/fengari',
  ];
  for (const c of candidates) {
    try { return require(c); } catch (e) { /* 继续尝试下一个 */ }
  }
  return null;
}

const fg = findFengari();
if (!fg) {
  console.log('（未找到 fengari，跳过 Lua 语法验证）');
  console.log('  安装方式: npm i fengari');
  process.exit(0);
}

const { lua, lauxlib, lualib, to_luastring, to_jsstring } = fg;

let files = process.argv.slice(2);
if (files.length === 0) {
  files = ['render.lua', 'examples/selftest_merged.lua'];
}

let bad = 0;
for (const f of files) {
  if (!fs.existsSync(f)) {
    console.log('  跳过（文件不存在）: ' + f);
    continue;
  }
  const L = lauxlib.luaL_newstate();
  lualib.luaL_openlibs(L);
  const st = lauxlib.luaL_dofile(L, to_luastring(f));
  if (st !== lua.LUA_OK) {
    console.log('  ✗ ' + f + ' : ' + to_jsstring(lua.lua_tostring(L, -1)));
    bad++;
  } else {
    console.log('  ✓ ' + f + ' 语法正确');
  }
}

process.exit(bad === 0 ? 0 : 1);

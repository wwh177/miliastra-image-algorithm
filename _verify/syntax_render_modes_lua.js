const {lua,lauxlib,lualib,to_luastring,to_jsstring}=require('E:/DSHworker/ugc/luacheck/node_modules/fengari');
const L=lauxlib.luaL_newstate(); lualib.luaL_openlibs(L);
const st=lauxlib.luaL_dofile(L,to_luastring('C:/Users/Administrator/Desktop/最大对齐矩形合并压缩/render_modes.lua'));
if(st!==lua.LUA_OK){console.error(to_jsstring(lua.lua_tostring(L,-1)));process.exit(1);}

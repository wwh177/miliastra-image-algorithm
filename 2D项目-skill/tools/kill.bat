@echo off
rem ============================================================
rem  kill.bat -- Emergency rescue: replace scripts with an empty stub
rem
rem  When to use:
rem    The level freezes / rebuilds infinitely / exceeds the control
rem    limit as soon as you enter it, and restarting the game does not
rem    help (the script rebuilds on every level entry).
rem
rem  Usage:  kill.bat [level_id]
rem  Effect: empties every script under external_lua_file, keeping a
rem          .killed.bak copy. The .gil file is NOT touched.
rem  Restore: rename the .killed.bak back.
rem
rem  NOTE: pure ASCII on purpose (same reason as deploy.bat).
rem ============================================================
setlocal enabledelayedexpansion
chcp 65001 >nul

set "LEVEL=%~1"
if "%LEVEL%"=="" set "LEVEL=1073741837"

set "MIHOYO=%USERPROFILE%\AppData\LocalLow\miHoYo"
if not exist "%MIHOYO%" (
    echo [ERROR] Not found: %MIHOYO%
    pause
    exit /b 1
)

set "DST="
for /d %%G in ("%MIHOYO%\*") do (
    if not "!DST!"=="" goto :found
    if exist "%%G\BeyondLocal" (
        for /d %%U in ("%%G\BeyondLocal\*") do (
            if not "!DST!"=="" goto :found
            if exist "%%U\Beyond_Local_Save_Level\%LEVEL%\external_lua_file" (
                set "DST=%%U\Beyond_Local_Save_Level\%LEVEL%\external_lua_file"
            )
        )
    )
)
:found

if "!DST!"=="" (
    echo [ERROR] No BeyondLocal folder contains level %LEVEL%
    pause
    exit /b 1
)

echo ======================================
echo   Emergency rescue for level %LEVEL%
echo   Folder: !DST!
echo ======================================
echo.

for %%F in ("!DST!\*.lua") do (
    if /i not "%%~xF"==".bak" (
        echo   processing %%~nxF
        copy /y "%%F" "%%F.killed.bak" >nul
        > "%%F" echo -- emergency stub (kill.bat)
        >> "%%F" echo local function log(...) print("[kill] " .. table.concat({...}, " ")) end
        >> "%%F" echo function OnStart() log("stub loaded, no controls will be created") end
        >> "%%F" echo function OnUpdate(dt) end
        >> "%%F" echo function OnDestroy() log("[kill] OnDestroy") end
    )
)

echo.
echo   Done. It is now safe to enter the level.
echo   To restore: rename the .killed.bak file back.
echo.
pause
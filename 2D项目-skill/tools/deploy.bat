@echo off
rem ============================================================
rem  deploy.bat -- One-click deploy for qianxing 2D projects
rem
rem  Usage:
rem    1) Drag your script.lua onto this .bat
rem    2) Or:  deploy.bat your_script.lua [level_id]
rem
rem  What it does:
rem    - auto-detect the BeyondLocal folder that contains the level
rem    - back up the existing script, copy the new one
rem    - verify SHA256 to make sure the editor did not overwrite it
rem
rem  NOTE: pure ASCII on purpose. cmd.exe parses .bat as ANSI (GBK on CN
rem        systems), so a UTF-8 .bat with non-ASCII text gets mangled
rem        (echo becomes cho).
rem ============================================================
setlocal enabledelayedexpansion
chcp 65001 >nul

set "SRC=%~1"
set "LEVEL=%~2"
if "%LEVEL%"=="" set "LEVEL=1073741837"

if "%SRC%"=="" (
    echo [ERROR] Drag a .lua file onto this script, or run:
    echo         deploy.bat your_script.lua [level_id]
    pause
    exit /b 1
)
if not exist "%SRC%" (
    echo [ERROR] File not found: %SRC%
    pause
    exit /b 1
)

set "MIHOYO=%USERPROFILE%\AppData\LocalLow\miHoYo"
if not exist "%MIHOYO%" (
    echo [ERROR] Not found: %MIHOYO%
    pause
    exit /b 1
)

rem ---- 1) find the BeyondLocal folder that contains this level ----
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
    echo         Searched under: %MIHOYO%
    echo         Check the level id, or enter the level once so its folder exists.
    pause
    exit /b 1
)

rem ---- 2) keep the same file name as the existing script (#50.1.3) ----
set "TARGET="
for %%F in ("!DST!\*.lua") do (
    if "!TARGET!"=="" set "TARGET=%%~nxF"
)
if "!TARGET!"=="" (
    echo [WARN] No .lua in target folder, using source file name.
    for %%F in ("%SRC%") do set "TARGET=%%~nxF"
)

echo ======================================
echo   Source : %SRC%
echo   Level  : %LEVEL%
echo   Target : !DST!
echo   File   : !TARGET!
echo ======================================
echo.

echo [1/3] Backing up ...
if exist "!DST!\!TARGET!" (
    copy /y "!DST!\!TARGET!" "!DST!\!TARGET!.bak" >nul
    echo       saved as !TARGET!.bak
) else (
    echo       no existing file, skipped
)

echo [2/3] Copying ...
copy /y "%SRC%" "!DST!\!TARGET!" >nul
if errorlevel 1 (
    echo [ERROR] Copy failed
    pause
    exit /b 1
)

echo [3/3] Verifying hash ...
set "SRC_HASH="
for /f "skip=1 delims=" %%H in ('certutil -hashfile "%SRC%" SHA256') do (
    if "!SRC_HASH!"=="" set "SRC_HASH=%%H"
)
set "DST_HASH="
for /f "skip=1 delims=" %%H in ('certutil -hashfile "!DST!\!TARGET!" SHA256') do (
    if "!DST_HASH!"=="" set "DST_HASH=%%H"
)
if "!SRC_HASH!"=="!DST_HASH!" (
    echo       OK, hash matched
) else (
    echo       [WARN] Hash mismatch! The editor may have overwritten it. Retry.
)

echo.
echo ======================================
echo   Done.
echo   Now in the editor: exit level, then re-enter level.
echo   (No editor restart needed, about 20 seconds per round.)
echo ======================================
echo.
pause
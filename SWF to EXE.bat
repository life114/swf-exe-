@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title SWF 转 EXE（拖拽批量转换）

set "HERE=%~dp0"

rem ---------- 找 Python ----------
set "PYEXE="
where py >nul 2>&1 && set "PYEXE=py"
if not defined PYEXE (
    where python >nul 2>&1 && set "PYEXE=python"
)
if not defined PYEXE (
    echo [X] 找不到 Python，请先安装 Python 3 并勾选 Add Python to PATH
    pause
    exit /b 1
)

rem ---------- 没拖文件时显示说明 ----------
if "%~1"=="" (
    echo ============================================================
    echo   SWF 转 EXE
    echo ============================================================
    echo.
    echo   用法：把 .swf 文件【拖到这个 bat 上】
    echo         可以一次拖多个，会依次转换
    echo.
    echo   生成的 EXE 放在 SWF 旁边，双击即可玩。
    echo.
    echo   默认用桌面的 flash播放器.exe 作为内核。
    echo   播放器不在桌面时，请改用命令行指定 --player
    echo.
    pause
    exit /b 0
)

rem ---------- 依次转换 ----------
set /a OK=0
set /a FAIL=0

:loop
if "%~1"=="" goto done

echo.
echo ============================================================
echo   正在转换: %~nx1
echo ============================================================

%PYEXE% "%HERE%swf2exe.py" "%~1" --out-dir "%~dp1"
if errorlevel 1 (
    echo   [失败] %~nx1
    set /a FAIL+=1
) else (
    set /a OK+=1
)

shift
goto loop

:done
echo.
echo ============================================================
echo   完成：成功 !OK! 个，失败 !FAIL! 个
echo ============================================================
pause

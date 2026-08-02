@echo off
REM Ainos OS - Windows 一键安装脚本
REM 用法: install.bat

setlocal enabledelayedexpansion
echo ============================================
echo   Ainos OS - Windows 一键安装
echo ============================================
echo.

REM 检查是否以管理员权限运行
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARN] 建议以管理员权限运行此脚本
    echo        右键 - "以管理员身份运行"
    echo.
)

REM 设置路径
set AINOS_HOME=%~dp0..
set DAEMON_DIR=%AINOS_HOME%\system-services\ai-daemon
set CONFIG_DIR=%AINOS_HOME%\configs
set MODELS_DIR=%AINOS_HOME%\models
set DATA_DIR=%AINOS_HOME%\data\contexts
set LOGS_DIR=%AINOS_HOME%\logs

REM 创建目录
echo [1/5] 创建目录结构...
if not exist "%MODELS_DIR%" mkdir "%MODELS_DIR%"
if not exist "%DATA_DIR%" mkdir "%DATA_DIR%"
if not exist "%LOGS_DIR%" mkdir "%LOGS_DIR%"
echo   OK

REM 检查 Rust
echo [2/5] 检查 Rust 工具链...
where rustc >nul 2>&1
if %errorlevel% neq 0 (
    echo   Rust 未安装。
    echo   请访问 https://rustup.rs 安装 Rust
    pause
    exit /b 1
)
echo   Rust:
rustc --version
echo   OK

REM 编译守护进程
echo [3/5] 编译 ai-daemon...
cd /d "%DAEMON_DIR%"
cargo build --release
if %errorlevel% neq 0 (
    echo   编译失败！
    pause
    exit /b 1
)
echo   OK

REM 注册 Windows 服务（可选）
echo [4/5] 注册 Windows 服务...
sc query AinosDaemon >nul 2>&1
if %errorlevel% equ 0 (
    echo   服务已存在，跳过
) else (
    sc create AinosDaemon binPath= "%DAEMON_DIR%\target\release\ai-daemon.exe -c %CONFIG_DIR%\ai-daemon.toml -v" start= auto
    if %errorlevel% equ 0 (
        echo   服务已注册: AinosDaemon
        echo   启动服务: sc start AinosDaemon
    ) else (
        echo   [WARN] 服务注册失败（可能需要管理员权限）
    )
)
echo   OK

REM 完成
echo [5/5] 安装完成！
echo.
echo ============================================
echo   Ainos OS 安装成功！
echo ============================================
echo.
echo   启动守护进程:
echo     cd %DAEMON_DIR%
echo     target\release\ai-daemon.exe -c %CONFIG_DIR%\ai-daemon.toml -v
echo.
echo   或使用系统服务:
echo     sc start AinosDaemon
echo.
echo   运行验收测试:
echo     python %AINOS_HOME%\scripts\verification_test.py
echo.
echo   系统托盘:
echo     python %AINOS_HOME%\scripts\ainos_tray.py
echo.
echo   模型下载:
echo     python %AINOS_HOME%\scripts\download_model.py --list
echo.

pause
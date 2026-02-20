@echo off
setlocal EnableDelayedExpansion

REM ─────────────────────────────────────────────────────────────────────────────
REM  Signalis — Installer (Windows CMD)
REM  Double-click to run, or execute from the project folder:  install.bat
REM ─────────────────────────────────────────────────────────────────────────────

REM Always switch to the folder where this script lives so relative paths work
cd /d "%~dp0"

echo.
echo  ######  ##  ######  ##   ##  #####  ##     ##  ######
echo  ##      ##  ##      ###  ##  ##  ## ##     ##  ##
echo  ######  ##  ## ###  ## # ##  #####  ##     ##  ######
echo      ##  ##  ##  ##  ##  ###  ##  ## ##     ##      ##
echo  ######  ##  ######  ##   ##  ##  ## ######  ##  ######
echo.
echo  Installer  ·  Windows CMD
echo  ________________________________________
echo.

REM ── [1/4] Python ─────────────────────────────────────────────────────────────
echo [1/4] Checking Python...
echo.

REM Try python3 first, fall back to python
set PYTHON=
where python3 >nul 2>nul && set PYTHON=python3
if not defined PYTHON (
    where python >nul 2>nul && set PYTHON=python
)

if not defined PYTHON (
    echo  [!!] Python not found.
    echo.
    echo  Install Python 3.9+ from:
    echo    https://www.python.org/downloads/
    echo.
    echo  IMPORTANT: Check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

REM Check version (3.9+ required)
for /f "tokens=2" %%v in ('%PYTHON% --version 2^>^&1') do set PYTHON_VERSION=%%v
for /f "tokens=1,2 delims=." %%a in ("%PYTHON_VERSION%") do (
    set MAJOR=%%a
    set MINOR=%%b
)

if %MAJOR% LSS 3 (
    echo  [!!] Python 3.9+ required. Found: %PYTHON_VERSION%
    echo       Upgrade at https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)
if %MAJOR% EQU 3 if %MINOR% LSS 9 (
    echo  [!!] Python 3.9+ required. Found: %PYTHON_VERSION%
    echo       Upgrade at https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

echo  [OK] Python %PYTHON_VERSION%
echo.

REM ── [2/4] Virtual environment + dependencies ────────────────────────────────
echo [2/4] Installing dependencies...
echo.

if exist "venv\" (
    REM Check if the existing venv's Python is still functional
    if exist "venv\Scripts\python.exe" (
        venv\Scripts\python.exe --version >nul 2>nul
        if !errorlevel! neq 0 (
            echo  [--] Existing venv is broken -- recreating...
            rmdir /s /q venv
            %PYTHON% -m venv venv
            if !errorlevel! neq 0 (
                echo  [!!] Failed to create virtual environment.
                echo.
                pause
                exit /b 1
            )
            echo  [OK] Recreated virtual environment.
        ) else (
            echo  [--] Existing venv found -- reusing it.
            echo       ^(Delete the venv folder to start fresh.^)
        )
    ) else (
        echo  [--] Existing venv is incomplete -- recreating...
        rmdir /s /q venv
        %PYTHON% -m venv venv
        if !errorlevel! neq 0 (
            echo  [!!] Failed to create virtual environment.
            echo.
            pause
            exit /b 1
        )
        echo  [OK] Recreated virtual environment.
    )
) else (
    %PYTHON% -m venv venv
    if %errorlevel% neq 0 (
        echo  [!!] Failed to create virtual environment.
        echo       Make sure python3-venv is available and try again.
        echo.
        pause
        exit /b 1
    )
    echo  [OK] Created virtual environment.
)

call venv\Scripts\activate.bat

python -m pip install --upgrade pip --quiet --disable-pip-version-check

REM Capture pip output — show only on failure so normal runs stay clean
python -m pip install -e ".[all]" --disable-pip-version-check > "%TEMP%\signalis_pip.log" 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  [!!] Dependency installation failed:
    echo.
    type "%TEMP%\signalis_pip.log"
    del /q "%TEMP%\signalis_pip.log" >nul 2>nul
    echo.
    pause
    exit /b 1
)
del /q "%TEMP%\signalis_pip.log" >nul 2>nul

echo  [OK] Installed (Shaper + Connector -- full install).
echo.

REM Confirm the binary was created
if not exist "venv\Scripts\signalis.exe" (
    echo  [!!] signalis.exe not found after install -- pip install may have failed.
    echo.
    pause
    exit /b 1
)

REM ── [3/4] PATH configuration ────────────────────────────────────────────────
echo [3/4] Adding to PATH...
echo.

set "VENV_SCRIPTS=%~dp0venv\Scripts"

REM Read current user PATH from registry (may be empty on a fresh account)
set "USER_PATH="
for /f "tokens=2*" %%a in ('reg query "HKCU\Environment" /v Path 2^>nul') do set "USER_PATH=%%b"

echo !USER_PATH! | find /i "%VENV_SCRIPTS%" >nul 2>nul
if %errorlevel% neq 0 (
    if defined USER_PATH (
        REM setx has a 1024-character limit — use PowerShell to set PATH safely
        powershell -Command "[System.Environment]::SetEnvironmentVariable('Path', '%VENV_SCRIPTS%;' + [System.Environment]::GetEnvironmentVariable('Path', 'User'), 'User')" >nul 2>nul
        if !errorlevel! neq 0 (
            REM PowerShell unavailable — fall back to setx
            setx PATH "%VENV_SCRIPTS%;!USER_PATH!" >nul 2>nul
            if !errorlevel! neq 0 (
                echo  [!!] Could not update PATH automatically.
                echo       Add this folder to your PATH manually:
                echo       %VENV_SCRIPTS%
                echo.
                echo       Or use install.ps1 ^(PowerShell^) instead.
                goto :path_done
            )
        )
    ) else (
        setx PATH "%VENV_SCRIPTS%" >nul
    )
    echo  [OK] Added to PATH.
    echo  [--] Open a new terminal window for the change to take effect.
) else (
    echo  [OK] Already in PATH.
)
:path_done
echo.

REM ── [4/4] Configuration ─────────────────────────────────────────────────────
echo [4/4] Configuration...
echo.

if exist ".env" (
    echo  [--] .env already exists -- keeping your settings.
) else (
    if exist ".env.example" (
        copy .env.example .env >nul
        echo  [OK] Created .env from template.
    ) else (
        echo  [--] .env.example not found -- skipping .env creation.
    )
)
echo.

REM ── Done ─────────────────────────────────────────────────────────────────────
echo  ________________________________________
echo  Installation complete.
echo  ________________________________________
echo.

REM Check if API keys are set (need both Exa AND an AI provider)
set "HAS_EXA=0"
set "HAS_AI=0"
findstr /r "EXA_API_KEY=." .env >nul 2>nul && set "HAS_EXA=1"
findstr /r "OPENAI_API_KEY=." .env >nul 2>nul && set "HAS_AI=1"
findstr /r "ANTHROPIC_API_KEY=." .env >nul 2>nul && set "HAS_AI=1"

if "%HAS_EXA%"=="0" goto :setup_keys
if "%HAS_AI%"=="0" goto :setup_keys
goto :keys_ok

:setup_keys
echo  API keys not configured.
echo  Exa + an AI provider are needed for signals ^& context.
echo.
set /p run_setup="  Set up API keys now? [Y/n]: "
echo.
if /i "!run_setup!" neq "n" (
    venv\Scripts\signalis.exe setup
) else (
    echo  Run  signalis setup  whenever you are ready.
)
goto :done_keys

:keys_ok
echo  API keys are configured.
echo  Run  signalis setup  to update them.

:done_keys

echo.
echo  Launch with:
echo.
echo  1. Open a new terminal window
echo  2. signalis
echo.
pause

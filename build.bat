@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "VENV=%~dp0.venv-build"
set "PY=%VENV%\Scripts\python.exe"

echo.
echo ==========================================
echo        NEON VOID - WINDOWS BUILD
echo ==========================================
echo.

where py >nul 2>&1
if errorlevel 1 goto :no_launcher

if not exist "%PY%" (
    echo [1/5] Creating isolated Python 3.12 build environment...
    py -3.12 -m venv "%VENV%"
    if errorlevel 1 goto :python_error
)

echo [2/5] Installing build dependencies...
"%PY%" -m pip install --upgrade pip
if errorlevel 1 goto :failed
"%PY%" -m pip install --only-binary=pygame -r requirements.txt pyinstaller pillow
if errorlevel 1 goto :failed

echo [3/5] Checking source and running tests...
"%PY%" -m compileall -q .
if errorlevel 1 goto :failed
set "SDL_VIDEODRIVER=dummy"
set "SDL_AUDIODRIVER=dummy"
"%PY%" -m unittest discover -s tests -v
if errorlevel 1 goto :failed
set "SDL_VIDEODRIVER="
set "SDL_AUDIODRIVER="

echo [4/5] Creating icon and building standalone EXE...
"%PY%" make_icon.py
if errorlevel 1 goto :failed
"%PY%" -m PyInstaller --noconfirm --clean --onefile --windowed --name "NEON VOID" --icon "icon.ico" --add-data "icon.ico;." main.py
if errorlevel 1 goto :failed
if not exist "dist\NEON VOID.exe" goto :missing_exe

echo [5/5] Smoke-testing the packaged EXE...
set "SDL_VIDEODRIVER=dummy"
set "SDL_AUDIODRIVER=dummy"
"dist\NEON VOID.exe" --smoke-test
if errorlevel 1 goto :failed
set "SDL_VIDEODRIVER="
set "SDL_AUDIODRIVER="

echo.
echo BUILD COMPLETED SUCCESSFULLY!
echo.
echo EXE: %~dp0dist\NEON VOID.exe
echo.
explorer "%~dp0dist"
pause
exit /b 0

:no_launcher
echo Python Launcher (py.exe) was not found.
echo Install Python 3.12 x64 and enable "Python Launcher" in the installer.
goto :failed

:python_error
echo Could not create the Python 3.12 virtual environment.
echo Make sure Python 3.12 x64 is installed.
goto :failed

:missing_exe
echo PyInstaller finished but dist\NEON VOID.exe was not found.
goto :failed

:failed
echo.
echo BUILD FAILED. Read the error messages above.
pause
exit /b 1

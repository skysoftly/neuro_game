@echo off
setlocal
cd /d "%~dp0"

REM Pygame 2.6.1 has prebuilt Windows wheels for Python 3.12.
REM Python 3.15 is too new and makes pip try to compile Pygame from source.
set "PY=py -3.12"
%PY% --version >nul 2>&1
if errorlevel 1 goto :no_python

echo [1/4] Installing runtime and build dependencies with Python 3.12...
%PY% -m pip install --upgrade pip
if errorlevel 1 goto :failed
%PY% -m pip install --only-binary=pygame -r requirements.txt pyinstaller pillow
if errorlevel 1 goto :failed

echo [2/4] Creating application icon...
%PY% make_icon.py
if errorlevel 1 goto :failed

echo [3/4] Packaging NEON VOID...
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed --name "NEON VOID" --icon "icon.ico" --add-data "icon.ico;." main.py
if errorlevel 1 goto :failed

echo [4/4] Build complete.
echo Executable: dist\NEON VOID.exe
pause
exit /b 0

:no_python
echo.
echo Python 3.12 x64 was not found.
echo Install Python 3.12 (64-bit) from https://www.python.org/downloads/release/python-31210/
echo During installation, enable the Python Launcher option.
echo Then run build.bat again.
pause
exit /b 1

:failed
echo.
echo Build failed. Check the error above.
pause
exit /b 1

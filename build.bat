@echo off
setlocal
cd /d "%~dp0"

echo [1/4] Installing runtime and build dependencies...
py -3 -m pip install --upgrade pip
if errorlevel 1 goto :failed
py -3 -m pip install -r requirements.txt pyinstaller pillow
if errorlevel 1 goto :failed

echo [2/4] Creating application icon...
py -3 make_icon.py
if errorlevel 1 goto :failed

echo [3/4] Packaging NEON VOID...
py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --name "NEON VOID" --icon "icon.ico" --add-data "icon.ico;." main.py
if errorlevel 1 goto :failed

echo [4/4] Build complete.
echo Executable: dist\NEON VOID.exe
pause
exit /b 0

:failed
echo.
echo Build failed. Check the error above.
pause
exit /b 1

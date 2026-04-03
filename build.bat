@echo off
echo ============================================
echo   CiscoBackup - EXE Builder
echo   by: The Ronin Dev
echo ============================================
echo.

echo [1/3] Installing / upgrading dependencies...
python -m pip install --upgrade pyinstaller customtkinter netmiko pystray pillow schedule plyer
echo.

echo [2/3] Cleaning previous build...
if exist build   rmdir /s /q build
if exist dist    rmdir /s /q dist
echo.

echo [3/3] Building EXE...
python -m PyInstaller CiscoBackup.spec
echo.

if exist "dist\CiscoBackup.exe" (
    echo ============================================
    echo   SUCCESS!
    echo   Your EXE is ready at:
    echo   dist\CiscoBackup.exe
    echo ============================================
    explorer dist
) else (
    echo ============================================
    echo   BUILD FAILED - check errors above
    echo ============================================
)

pause

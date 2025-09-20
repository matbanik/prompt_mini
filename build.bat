@echo off
echo Building Prompt Mini executable...

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python is not installed or not in PATH
    pause
    exit /b 1
)

REM Check if PyInstaller is installed, install if not
python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    pip install pyinstaller
    if errorlevel 1 (
        echo Error: Failed to install PyInstaller
        pause
        exit /b 1
    )
)

REM Install required dependencies
echo Installing required dependencies...
pip install pandas reportlab python-docx wordcloud requests huggingface_hub

REM Create executable with PyInstaller
echo Creating executable...
pyinstaller --onefile --windowed --name "PromptMini" --exclude-module pytest prompt_mini.py

if errorlevel 1 (
    echo Error: Failed to create executable
    pause
    exit /b 1
)

echo.
echo Build completed successfully!
echo Executable created in: dist\PromptMini.exe
echo.
pause
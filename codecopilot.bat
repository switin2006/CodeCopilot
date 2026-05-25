@echo off
REM CodeCopilot launcher — run from any folder.
REM
REM Usage:
REM   codecopilot                       (operate on current directory)
REM   codecopilot --persona coder
REM   codecopilot --workdir D:\proj
REM
REM Add this folder to PATH so 'codecopilot' works system-wide:
REM   setx PATH "%PATH%;C:\Users\switi\OneDrive\Desktop\Code_Copilot\CodeCopilot"

setlocal
set "CODECOPILOT_DIR=%~dp0"
set "CODECOPILOT_DIR=%CODECOPILOT_DIR:~0,-1%"

REM Forward all args verbatim. cli.py handles --workdir / -C itself.
"%CODECOPILOT_DIR%\.venv\Scripts\python.exe" "%CODECOPILOT_DIR%\cli.py" %*
endlocal

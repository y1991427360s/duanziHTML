@echo off
rem Launcher for duanzi_dxf_tool.py
rem Keep this file pure ASCII with CRLF line endings, otherwise cmd.exe garbles it.
chcp 65001 >nul
cd /d "%~dp0"
set "PY=python"
where python >nul 2>nul || set "PY=py"
%PY% -u "%~dp0duanzi_dxf_tool.py"
if errorlevel 1 pause

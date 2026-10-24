@echo off
cd /d "%~dp0"
set "ZHIXU_DATA_DIR=%~dp0data"
if exist "release\win-unpacked\Zhixu.exe" (
  start "" "release\win-unpacked\Zhixu.exe"
  exit /b
)
if exist "release\Zhixu-0.3.0.exe" (
  start "" "release\Zhixu-0.3.0.exe"
  exit /b
)
call npm.cmd run build
if errorlevel 1 pause
if errorlevel 1 exit /b 1
call npm.cmd start

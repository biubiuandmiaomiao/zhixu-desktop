@echo off
cd /d "%~dp0"
if exist "release\Zhixu-0.1.0.exe" (
  start "" "release\Zhixu-0.1.0.exe"
  exit /b
)
if exist "release\win-unpacked\Zhixu.exe" (
  start "" "release\win-unpacked\Zhixu.exe"
  exit /b
)
call npm.cmd run build
if errorlevel 1 pause
if errorlevel 1 exit /b 1
call npm.cmd start

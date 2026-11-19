@echo off
REM FastSim 启动脚本（Windows）
cd /d "%~dp0backend"
echo Starting FastSim backend on http://127.0.0.1:8000 ...
python -m fastsim.app --host 127.0.0.1 --port 8000

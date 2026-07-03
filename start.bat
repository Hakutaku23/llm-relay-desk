@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul

call conda activate ollama
if errorlevel 1 (
  echo [ERROR] 无法激活 conda 环境 ollama。
  echo 请先执行: conda create -n ollama python=3.12
  pause
  exit /b 1
)

if not exist ".env" copy /Y ".env.example" ".env" >nul

python -c "import fastapi, uvicorn, httpx, dotenv" >nul 2>nul
if errorlevel 1 (
  echo 正在安装依赖...
  python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo [ERROR] 依赖安装失败。
    pause
    exit /b 1
  )
)

start "" "http://127.0.0.1:11434/ui/"
python app.py
pause

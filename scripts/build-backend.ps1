$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path $PSScriptRoot -Parent)
& '.\.venv\Scripts\python.exe' -m PyInstaller --noconfirm --onedir --name zhixu-backend --distpath build --workpath build/pyinstaller --collect-all yt_dlp --collect-all qdrant_client --collect-data mem0 --copy-metadata mem0ai --hidden-import mem0.llms.openai --hidden-import mem0.embeddings.openai --hidden-import mem0.vector_stores.qdrant --hidden-import mem0.configs.vector_stores.qdrant backend/main.py
if ($LASTEXITCODE -ne 0) { throw '后端打包失败' }

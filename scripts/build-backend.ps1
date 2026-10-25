$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path $PSScriptRoot -Parent)
$ffmpegCommand = (Get-Command ffmpeg -ErrorAction Stop).Source
$ffprobeCommand = (Get-Command ffprobe -ErrorAction Stop).Source
$ffmpegLicense = Join-Path (Split-Path (Split-Path $ffmpegCommand -Parent) -Parent) 'LICENSE'
if (-not (Test-Path -LiteralPath $ffmpegLicense)) { throw '构建需提供 FFmpeg 的许可证文件' }
$buildArguments = @('--noconfirm','--onedir','--name','zhixu-backend','--distpath','build','--workpath','build/pyinstaller',
    '--collect-all','yt_dlp','--collect-all','qdrant_client','--collect-data','mem0','--copy-metadata','mem0ai',
    '--collect-all','faster_whisper','--collect-all','ctranslate2','--collect-all','av','--collect-all','onnxruntime',
    '--collect-all','tokenizers','--collect-all','markdown_it','--collect-data','huggingface_hub','--copy-metadata','faster-whisper',
    '--copy-metadata','huggingface-hub','--copy-metadata','tokenizers','--copy-metadata','ctranslate2',
    '--copy-metadata','av','--copy-metadata','onnxruntime',
    '--add-binary',($ffmpegCommand+';ffmpeg_bin'),'--add-binary',($ffprobeCommand+';ffmpeg_bin'),
    '--add-data',($ffmpegLicense+';third-party'),
    '--hidden-import','mem0.vector_stores.qdrant','--hidden-import','mem0.configs.vector_stores.qdrant','backend/main.py')
& '.\.venv\Scripts\python.exe' -m PyInstaller @buildArguments
if ($LASTEXITCODE -ne 0) { throw '后端打包失败' }

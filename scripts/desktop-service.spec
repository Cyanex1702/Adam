from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs, copy_metadata
from pathlib import Path

root = Path(SPECPATH).parent
datas = collect_data_files('adam')
binaries = collect_dynamic_libs('onnxruntime')
hidden = collect_submodules('winrt') + collect_submodules('adam') + ['uvicorn.logging', 'uvicorn.loops.auto', 'uvicorn.protocols.http.auto', 'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan.on', 'win32crypt', 'pythoncom', 'win32com.client']
for package in ['faster_whisper', 'ctranslate2', 'av', 'kokoro_onnx', 'espeakng_loader', 'phonemizer', 'sherpa_onnx']:
    datas += collect_data_files(package)
    binaries += collect_dynamic_libs(package)
    hidden += collect_submodules(package)
for package in ['kokoro-onnx', 'faster-whisper', 'phonemizer', 'sherpa-onnx', 'sherpa-onnx-core']:
    datas += copy_metadata(package)
a = Analysis([str(root / 'scripts/desktop-entry.py')], pathex=[str(root / 'backend')], binaries=binaries, datas=datas, hiddenimports=hidden, excludes=['pytest', 'mypy', 'ruff', 'tkinter', 'matplotlib', 'IPython'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='adam-service', console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='backend')

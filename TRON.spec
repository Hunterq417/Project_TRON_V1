# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []
tmp_ret = collect_all('sounddevice')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pystray')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('keyboard')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('cv2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
# openwakeword ships its shared mel-spectrogram and embedding models as package
# data (resources/models/*.onnx). Without these the wake word cannot run at all:
# they are the frozen pretrained front-end every wake word sits on top of, and
# openwakeword loads them by path from inside its own package directory. They are
# downloaded on first use rather than shipped in the wheel, so if a fresh
# environment ever rebuilds and the wake word stops working, run
# `openwakeword.utils.download_models()` before building.
tmp_ret = collect_all('openwakeword')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
# pycaw drives Core Audio through comtypes, which builds its COM interface
# wrappers by generating modules at runtime. PyInstaller's import scanner
# cannot see code that does not exist yet, so the generated package has to be
# collected explicitly or volume control raises ImportError only in the frozen
# build — where it is hardest to notice.
tmp_ret = collect_all('comtypes')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pycaw')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
hiddenimports += ['psutil']
# The video clipper's ffmpeg: a free, open-source binary that imageio-ffmpeg ships as package data.
# Offline mode: speech recognised on this PC (Parakeet via onnx-asr; the model lives next to the exe in
# models\parakeet-tdt-0.6b-v2). LiveKit: WebRTC echo cancellation, a native library.
# Local mode's voice: Kokoro (model in models\kokoro next to the exe) and espeak-ng for pronunciation.
for _pkg in ('onnx_asr', 'livekit', 'kokoro_onnx', 'espeakng_loader', 'phonemizer', 'customtkinter', 'playwright', 'sherpa_onnx'):
    tmp_ret = collect_all(_pkg)
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('imageio_ffmpeg')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


# the Dust Orb face (three.js page, rendered by a headless Brave)
datas += [('src/assets/dust_orb', 'assets/dust_orb')]

a = Analysis(
    ['src/main.py'],
    pathex=['src'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='TRON',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

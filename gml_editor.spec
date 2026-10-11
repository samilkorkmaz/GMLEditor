# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []
tmp_ret = collect_all('vtk')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pyvista')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
# GeoTIFF reading (compressed/tiled). imagecodecs ships many binary codec
# extensions that static analysis misses, so collect it wholesale.
# The Qt GUI (top panel) needs pyvistaqt + qtpy + PyQt5 (and its plugins).
for _pkg in ('tifffile', 'imagecodecs', 'pyvistaqt', 'qtpy', 'PyQt5'):
    try:
        tmp_ret = collect_all(_pkg)
        datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
    except Exception:
        pass  # optional: app falls back (Pillow for TIFFs, basic viewer w/o Qt)

# Large transitive dependencies that pyvista can pull in but this app never
# imports at runtime (verified by probing sys.modules). Excluding them keeps the
# bundle smaller. matplotlib and PIL are kept (colormaps/fonts, screenshots);
# the Qt stack is now kept too (needed by the GUI panel), which adds ~130 MB.
EXCLUDES = [
    'PyQt6', 'PySide2', 'PySide6',
    'scipy', 'llvmlite', 'numba', 'pandas', 'lxml',
    'pydantic', 'pydantic_core',
    'trame', 'imageio',
    'IPython', 'jupyter', 'notebook', 'sphinx', 'pytest',
]


a = Analysis(
    ['run_gml_editor.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='gml_editor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='gml_editor',
)

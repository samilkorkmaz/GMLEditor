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
for _pkg in ('tifffile', 'imagecodecs'):
    try:
        tmp_ret = collect_all(_pkg)
        datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
    except Exception:
        pass  # optional: the app falls back to Pillow for simple TIFFs

# NOTE: pyvistaqt/qtpy/PyQt are intentionally NOT collected. The app uses a
# plain pyvista.Plotter (no Qt backend), so the Qt stack is dead weight (~131 MB).

# Large transitive dependencies that pyvista can pull in but this app never
# imports at runtime (verified by probing sys.modules after a full render +
# screenshot). Excluding them cuts the bundle by ~320 MB. matplotlib and PIL
# are deliberately kept: pyvista uses matplotlib for colormaps/fonts and PIL
# for screenshots.
EXCLUDES = [
    'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'pyvistaqt', 'qtpy',
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

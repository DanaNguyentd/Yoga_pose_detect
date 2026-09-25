# PyInstaller build definition.
#
#   pip install -r requirements-build.txt
#   pyinstaller build.spec
#
# Produces a self-contained application under dist/ that bundles Python, OpenCV
# and the web interface, so whoever runs it installs nothing. Build on the
# operating system you are targeting: PyInstaller cannot cross-compile.

import sys

block_cipher = None

analysis_step = Analysis(
    ["app.py"],
    pathex=[],
    binaries=[],
    # The HTML interface travels with the binary and is found via resource_path()
    datas=[("web", "web")],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    # Nothing in this project uses these, and they are large
    excludes=["matplotlib", "scipy", "pandas", "PyQt5", "PySide2", "PySide6"],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(analysis_step.pure, analysis_step.zipped_data, cipher=block_cipher)

executable = EXE(
    pyz,
    analysis_step.scripts,
    [],
    exclude_binaries=True,
    name="YogaPoseExtractor",
    debug=False,
    strip=False,
    upx=False,
    console=False,          # no terminal window behind the app
    disable_windowed_traceback=False,
)

collection = COLLECT(
    executable,
    analysis_step.binaries,
    analysis_step.zipfiles,
    analysis_step.datas,
    strip=False,
    upx=False,
    name="YogaPoseExtractor",
)

# macOS wants a bundle rather than a bare folder, so it appears as one app
if sys.platform == "darwin":
    app = BUNDLE(
        collection,
        name="YogaPoseExtractor.app",
        icon=None,
        bundle_identifier="com.dananguyentd.yogaposeextractor",
        info_plist={
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "10.15",
        },
    )

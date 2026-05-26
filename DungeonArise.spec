# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    # 1. Tell PyInstaller to copy your assets folder into the build
    datas=[
        ('assets', 'assets'), 
    ],
    # 2. Force PyInstaller to include hidden dependencies
    hiddenimports=[
        'websockets',
        'gltf',
        'simplepbr',
        'panda3d',
        'panda3d.core',
        'panda3d.direct',
        'panda3d.interrogatedb',
        'direct.showbase.ShowBase',
        'direct.directnotify.Notifier',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DungeonArise',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True, # Set to True if you want a CMD window to debug crashes
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='DungeonArise',
)
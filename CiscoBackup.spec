# CiscoBackup.spec
# PyInstaller spec file — single .exe, no console window
# Run: pyinstaller CiscoBackup.spec

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# customtkinter ships its themes/images as data files — must be bundled
ctk_datas = collect_data_files("customtkinter")

a = Analysis(
    ["cisco_backup_gui.py"],
    pathex=[],
    binaries=[],
    datas=ctk_datas,
    hiddenimports=[
        # pystray Windows backend
        "pystray._win32",
        # plyer Windows notification backend
        "plyer.platforms.win.notification",
        # netmiko transports
        "netmiko.cisco.cisco_ios",
        "netmiko.cisco.cisco_ios_telnet",
        # PIL / Pillow
        "PIL._tkinter_finder",
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="CiscoBackup",         # output filename
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                   # compress — set False if UPX not installed
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,              # no black console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="icon.ico",                  # put "icon.ico" path here if you have one
)

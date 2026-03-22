"""
setup.py — py2app configuration for building Murmurate.app.

Build a standalone macOS app bundle:
    cd menubar
    pip3 install py2app
    python3 setup.py py2app

The resulting app is in dist/Murmurate.app and can be moved to /Applications
or launched from anywhere. It runs as a menu bar-only app (no dock icon).
"""

from setuptools import setup

APP = ["murmurate_menubar.py"]
DATA_FILES = []

OPTIONS = {
    "argv_emulation": False,
    # LSUIElement=True makes it a menu bar-only app (no Dock icon)
    "plist": {
        "LSUIElement": True,
        "CFBundleName": "Murmurate",
        "CFBundleDisplayName": "Murmurate",
        "CFBundleIdentifier": "cloud.1507.murmurate.menubar",
        "CFBundleVersion": "0.2.0",
        "CFBundleShortVersionString": "0.2.0",
        "NSHumanReadableCopyright": "1507 Systems",
    },
    "packages": ["rumps"],
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)

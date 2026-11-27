"""Build the standalone Windows x64 installer with python setup.py bdist_msi."""

import sys
from importlib.metadata import distribution
from pathlib import Path

from cx_Freeze import Executable, setup


VERSION = "0.1.0"
licenses = [(Path(sys.base_prefix, "LICENSE.txt"), "share/licenses/python/LICENSE.txt")]
for package in ("numpy", "PyAudioWPatch", "capturekit", "soxr", "websockets"):
    dist = distribution(package)
    for entry in dist.files or ():
        if entry.parts[0].endswith(".dist-info") and entry.parts[1:2] == ("licenses",):
            licenses.append((dist.locate_file(entry), str(Path("share/licenses", package, *entry.parts[2:]))))

setup(
    name="VRC Transf",
    version=VERSION,
    author="zengxhzz",
    description="Desktop subtitles and microphone translation for VRChat",
    url="https://github.com/zengxhzz/vrc_transf",
    packages=["vrc_transf"],
    options={
        "build_exe": {
            "include_msvcr": True,
            "include_files": licenses,
            "replace_paths": [("*", "")],
            "includes": ["capturekit._backends.windows.api", "pyaudiowpatch"],
            "excludes": ["unittest", "test", "setuptools", "pip"],
        },
        "bdist_msi": {
            "product_name": "VRC Transf",
            "output_name": f"VRC-Transf-{VERSION}-windows-x64.msi",
            "upgrade_code": "{9C747FBF-D2F5-4A75-A482-A0B5D8B34FB9}",
            "initial_target_dir": r"[LocalAppDataFolder]Programs\VRC Transf",
            "directories": [("ProgramMenuFolder", "TARGETDIR", ".")],
            "all_users": False,
        },
    },
    executables=[
        Executable(
            "packaging/windows/launcher.py",
            base="gui",
            target_name="VRC Transf",
            shortcut_name="VRC Transf",
            shortcut_dir="ProgramMenuFolder",
        )
    ],
)

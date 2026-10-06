# PyInstaller spec: one-folder, windowed build of College Fit Advisor.
# Build from the repo root:  pyinstaller packaging/cfa.spec --noconfirm
# Ships code + the bundled registry (pointers only). Test fixtures are never included.
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))  # noqa: F821 (SPECPATH is injected by PyInstaller)

datas = [
    (os.path.join(ROOT, "registry", "schools.yaml"), "registry"),
    (os.path.join(ROOT, "src", "cfa", "ui", "icon.png"), os.path.join("cfa", "ui")),
]
datas += collect_data_files("certifi")  # CA bundle so HTTPS works on clean Windows installs

hiddenimports = collect_submodules("keyring.backends") + ["win32ctypes.core"]

a = Analysis(
    [os.path.join(ROOT, "packaging", "launcher.py")],
    pathex=[os.path.join(ROOT, "src")],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=[
        "tests", "pytest", "respx", "_pytest", "pytestqt", "mypy", "ruff",
        "tkinter", "IPython", "PyQt5", "PyQt6",
        "PySide6.Qt3DCore", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQuick",
        "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CollegeFitAdvisor",
    console=False,  # windowed
    icon=os.path.join(ROOT, "packaging", "cfa.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="CollegeFitAdvisor")

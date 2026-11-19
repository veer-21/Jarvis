# PyInstaller spec for the JARVIS backend. Build with:  python scripts\build_installer.py
# (or: pyinstaller packaging\jarvis_backend.spec --noconfirm --distpath packaging\dist --workpath packaging\build)
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

hiddenimports = (
    collect_submodules("api")
    + collect_submodules("core")
    + collect_submodules("tools")
    + collect_submodules("chromadb")
    + collect_submodules("uvicorn")
    + ["onnxruntime", "tokenizers", "win32cred", "win32crypt", "pywintypes", "pyttsx3.drivers", "pyttsx3.drivers.sapi5"]
)

datas = (
    collect_data_files("chromadb")
    + collect_data_files("google.genai")
    + collect_data_files("certifi")
    + [(os.path.join(ROOT, "desktop", "dist"), "ui")]
)

# Heavy optional features are installed separately (voice add-on, browser automation).
excludes = ["torch", "torchaudio", "faster_whisper", "ctranslate2", "tensorflow", "matplotlib",
            "IPython", "notebook", "tkinter", "playwright", "pytest"]

a = Analysis(
    [os.path.join(ROOT, "packaging", "backend_entry.py")],
    pathex=[ROOT],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="jarvis-backend", console=True,  # Electron spawns it hidden (windowsHide)
          icon=os.path.join(ROOT, "desktop", "assets", "icon.ico"))
coll = COLLECT(exe, a.binaries, a.datas, name="jarvis-backend")

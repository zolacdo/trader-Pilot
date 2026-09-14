# -*- mode: python ; coding: utf-8 -*-
"""Packaging PyInstaller du Bridge TradePilot (CDC section 58).

Produit un executable Windows autonome : plus besoin d'installer Python ni les
dependances sur la machine cible. MetaTrader 5 lui-meme n'est evidemment pas
embarque, il reste a installer separement.

Construction :
    .\\scripts\\build_bridge_exe.ps1

Points de vigilance traites ici :
  - uvicorn charge ses boucles et protocoles par import dynamique : PyInstaller
    ne peut pas les deviner, ils sont declares en imports caches ;
  - le dialecte SQLite asynchrone (aiosqlite) est lui aussi charge par nom ;
  - le worker MetaTrader utilise multiprocessing en mode spawn, ce qui relance
    l'executable : app/main.py appelle freeze_support() pour cela ;
  - aucun secret n'est embarque, le fichier .env reste a cote de l'executable.
"""

from PyInstaller.utils.hooks import collect_all, collect_submodules

# MetaTrader5 s'appuie sur numpy, dont le coeur natif ne se collecte pas tout
# seul : sans cela l'executable demarre mais echoue sur
# "numpy._core.multiarray failed to import", et le Bridge ne peut plus trader.
numpy_datas, numpy_binaries, numpy_hidden = collect_all("numpy")
mt5_datas, mt5_binaries, mt5_hidden = collect_all("MetaTrader5")

hidden_imports = [
    # Chargement dynamique par uvicorn
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.logging",
    # Base de donnees
    "aiosqlite",
    "sqlalchemy.dialects.sqlite",
    "sqlalchemy.dialects.sqlite.aiosqlite",
    # Integrations
    "MetaTrader5",
    "cryptography",
    # Le worker MT5 est importe par le processus enfant, pas par le parent
    "app.services.mt5._child_process",
]

# Toute l'application et Telethon (nombreux sous-modules charges par nom).
hidden_imports += collect_submodules("app")
hidden_imports += collect_submodules("telethon")
hidden_imports += collect_submodules("pydantic")
hidden_imports += numpy_hidden + mt5_hidden

analysis = Analysis(
    ["app/main.py"],
    pathex=["."],
    binaries=numpy_binaries + mt5_binaries,
    datas=numpy_datas + mt5_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Allege l'executable : rien de tout cela n'est utilise par le Bridge.
    excludes=["tkinter", "matplotlib", "PIL", "pytest", "mypy", "ruff", "IPython"],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="TradePilotBridge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # Console visible : le code d'appairage s'y affiche au demarrage.
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

collect = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="TradePilotBridge",
)

# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for FastAPI server
This bundles the FastAPI server and all its dependencies into a standalone executable
"""

import os
import sys
import importlib.util
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Collect all hidden imports that PyInstaller might miss
hiddenimports = [
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'fastapi',
    'pydantic',
    'starlette',
    'psutil',
    'psutil._psutil_osx',
    'psutil._psutil_posix',
    'dateutil',
    'dateutil.parser',
    'dateutil.tz',
    'PIL',
    'PIL.Image',
    'PIL.ImageDraw',
    'PIL.ImageFont',
    'reportlab',
    'reportlab.lib',
    'reportlab.lib.colors',
    'reportlab.lib.styles',
    'browser_use',
    'browser_use.agent',
    'browser_use.agent.prompts',
]

# Decide which automation library to bundle based on config
def _resolve_automation_lib():
    abs_cfg = os.path.normpath(r'd:/yuki_kingdom/jobhuntr/jobhuntr-v2/backend/constants.py')
    lib = None
    try:
        if os.path.exists(abs_cfg):
            spec = importlib.util.spec_from_file_location('app_config', abs_cfg)
            if spec and spec.loader:
                cfg = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(cfg)  # type: ignore
                val = getattr(cfg, 'AUTOMATION_LIB', None)
                if isinstance(val, str) and val:
                    lib = val.lower()
        if not lib:
            try:
                from constants import AUTOMATION_LIB as _LOCAL_LIB  # type: ignore
                if isinstance(_LOCAL_LIB, str) and _LOCAL_LIB:
                    lib = _LOCAL_LIB.lower()
            except Exception:
                pass
        if not lib:
            lib = os.environ.get('AUTOMATION_LIB', 'playwright').lower()
    except Exception:
        lib = 'playwright'
    # Always use playwright (patchright is no longer supported)
    return 'playwright'

AUTOMATION_LIB = _resolve_automation_lib()

# Collect submodules and data files only for the selected automation library
hiddenimports += collect_submodules(AUTOMATION_LIB)

# Explicitly add playwright modules that might be missed
if AUTOMATION_LIB == 'playwright':
    hiddenimports += [
        'playwright.sync_api',
        'playwright._impl._transport',
        'playwright._impl._api_structures',
        'playwright._impl._connection',
        'playwright._impl._driver',
        'playwright._impl._errors',
        'playwright._impl._helper',
        'playwright._impl._network',
        'playwright._impl._page',
        'playwright._impl._browser',
        'playwright._impl._browser_context',
        'playwright._impl._cdp_session',
        'playwright._impl._element_handle',
        'playwright._impl._frame',
        'playwright._impl._js_handle',
        'playwright._impl._locator',
        'playwright._impl._route',
        'playwright._impl._wait_helper',
    ]

# Collect data files for packages that need them
datas = []
datas += collect_data_files(AUTOMATION_LIB)
datas += collect_data_files('fastapi')

# Include browser-use prompt templates (system_prompt.md, etc.)
datas += collect_data_files('browser_use')

# Include Jinja template files for autonomous search bot and ATS marker
datas.append(('autonomous_search_bot/prompts', 'autonomous_search_bot/prompts'))
datas.append(('shared/ats_marker/prompts', 'shared/ats_marker/prompts'))

# Force include PIL/Pillow submodules and data files
hiddenimports += collect_submodules('PIL')
datas += collect_data_files('PIL')

a = Analysis(
    ['fastapi_server.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude unnecessary modules to reduce size
        'matplotlib',
        'numpy',
        'pandas',
        'tkinter',
        'IPython',
        'jupyter',
    ],
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
    name='fastapi_server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # Console app (not windowed)
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
    upx=False,
    upx_exclude=[],
    name='fastapi_server',
)

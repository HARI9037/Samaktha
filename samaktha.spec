# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules
from pathlib import Path


a = Analysis(
    ['app/cli.py'],
    pathex=[],
    binaries=[],
    datas=[],
    # DDGS lazy-loads its implementation and engine modules at runtime.
    hiddenimports=collect_submodules(
        'ddgs',
        filter=lambda name: not name.startswith('ddgs.api_server') and name != 'ddgs.cli',
    ),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

# Hooks for the document/OCR stack may classify package source as runtime
# data.  The pilot artifact must contain executable modules in PYZ, not exposed
# source, bytecode, runtime databases/keys, or editable-install provenance.
_prohibited_data_suffixes = {'.py', '.pyc', '.pyo', '.db', '.key'}
a.datas = [
    entry
    for entry in a.datas
    if not any(entry[0].lower().endswith(suffix) for suffix in _prohibited_data_suffixes)
    and not entry[0].lower().endswith('direct_url.json')
]

# importlib.metadata needs the distribution headers for the canonical version,
# but editable-install METADATA embeds README text (including development
# command paths).  Preserve only the standards-compliant metadata headers in
# the public artifact; the repository README remains outside the executable.
for index, entry in enumerate(a.datas):
    destination, source, typecode = entry
    normalized_destination = destination.replace('\\', '/').lower()
    if normalized_destination.startswith('samaktha_core-') and normalized_destination.endswith('.dist-info/metadata'):
        metadata_headers = Path(source).read_text(encoding='utf-8').split('\n\n', 1)[0] + '\n'
        safe_metadata = Path('build') / 'packaging-metadata' / 'METADATA'
        safe_metadata.parent.mkdir(parents=True, exist_ok=True)
        safe_metadata.write_text(metadata_headers, encoding='utf-8')
        a.datas[index] = (destination, str(safe_metadata.resolve()), typecode)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='samaktha',
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
    name='samaktha',
)

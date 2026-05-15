# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['main_gui.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=[
        # PyQt6 (GUI)
        'PyQt6',
        'PyQt6.QtCore',
        'PyQt6.QtWidgets',
        'PyQt6.QtGui',
        'PyQt6.QtNetwork',
        'PyQt6.QtSvg',
        'PyQt6.QtPrintSupport',
        # Selenium & Chrome
        'selenium',
        'selenium.webdriver',
        'selenium.webdriver.chrome',
        'selenium.webdriver.chrome.service',
        'selenium.webdriver.chrome.options',
        'selenium.webdriver.common',
        'selenium.webdriver.common.by',
        'selenium.webdriver.common.action_chains',
        'selenium.webdriver.support',
        'selenium.webdriver.support.ui',
        'selenium.webdriver.support.expected_conditions',
        'webdriver_manager',
        'webdriver_manager.chrome',
        'webdriver_manager.core',
        # Данные & Парсинг
        'pandas',
        'pandas.core',
        'pandas.core.arrays',
        'pandas._libs',
        'pandas._libs.tslibs',
        'openpyxl',
        'openpyxl.cell',
        'openpyxl.styles',
        'openpyxl.workbook',
        'openpyxl.xml',
        'bs4',
        'lxml',
        'lxml.html',
        'lxml.etree',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'jupyter',
        'matplotlib',
        'scipy',
        'IPython',
        'PyQt5',
        'PySide2',
        'PySide6',
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
    exclude_binaries=True,  # Обязательно для создания .app на macOS
    name='YandexParser',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # Скрывает окно терминала
    disable_windowed_traceback=False,
    target_arch=None,       # Auto: x86_64 или arm64
    codesign_identity=None,
    entitlements_file=None,
    icon=None,              # Укажите 'app_icon.icns' или 'app_icon.ico' при наличии
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='YandexParser',
)

#  macOS: создание .app бандла (запускается только на macOS)
app = BUNDLE(
    coll,
    name='YandexParser.app',
    icon=None,
    bundle_identifier='com.yandexparser.app',
    info_plist={
        'NSHighResolutionCapable': 'True',
        'LSBackgroundOnly': 'False',
        'CFBundleShortVersionString': '1.0.0',
        'CFBundleVersion': '1',
        'NSRequiresAquaSystemAppearance': 'True',  # Поддержка тёмной темы Big Sur+
    },
)
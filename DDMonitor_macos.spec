# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

a_bilibili_hiddenimports = collect_submodules('bilibili_api.clients')

block_cipher = None

a = Analysis(['DD监控室.py'],
             pathex=[],
             binaries=[
             ],
             datas=[
                ('resources/splash.jpg', 'resources'),
                ('resources/vtb.csv', 'resources'),
            ],
             hiddenimports=a_bilibili_hiddenimports,
             hookspath=[],
             runtime_hooks=[],
             excludes=[
                # PySide6 — 只保留 QtCore/QtGui/QtWidgets/QtOpenGLWidgets
                'PySide6.Qt3DAnimation',
                'PySide6.Qt3DCore',
                'PySide6.Qt3DExtras',
                'PySide6.Qt3DInput',
                'PySide6.Qt3DLogic',
                'PySide6.Qt3DRender',
                'PySide6.QAxContainer',
                'PySide6.QtBluetooth',
                'PySide6.QtCharts',
                'PySide6.QtDataVisualization',
                'PySide6.QtDBus',
                'PySide6.QtDesigner',
                'PySide6.QtGraphs',
                'PySide6.QtHelp',
                'PySide6.QtLocation',
                'PySide6.QtMultimedia',
                'PySide6.QtMultimediaWidgets',
                'PySide6.QtNetwork',
                'PySide6.QtNetworkAuth',
                'PySide6.QtNfc',
                'PySide6.QtOpenGL',
                'PySide6.QtPdf',
                'PySide6.QtPdfWidgets',
                'PySide6.QtPositioning',
                'PySide6.QtPrintSupport',
                'PySide6.QtQml',
                'PySide6.QtQuick',
                'PySide6.QtQuick3D',
                'PySide6.QtQuickWidgets',
                'PySide6.QtRemoteObjects',
                'PySide6.QtSensors',
                'PySide6.QtSerialPort',
                'PySide6.QtSql',
                'PySide6.QtSvg',
                'PySide6.QtSvgWidgets',
                'PySide6.QtTest',
                'PySide6.QtTextToSpeech',
                'PySide6.QtWebChannel',
                'PySide6.QtWebEngineCore',
                'PySide6.QtWebEngineQuick',
                'PySide6.QtWebEngineWidgets',
                'PySide6.QtWebSockets',
                'PySide6.QtWinExtras',
                'PySide6.QtXml',
                'PySide6.QtXmlPatterns'
             ],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)
pyz = PYZ(a.pure, a.zipped_data,
             cipher=block_cipher)
exe = EXE(pyz,
          a.scripts,
          [],
          exclude_binaries=True,
          name='DDMonitor',
          debug=False,
          bootloader_ignore_signals=False,
          strip=False,
          upx=False,
          icon='favicon.ico',
          console=False )

coll = COLLECT(exe,
               a.binaries,
               a.zipfiles,
               a.datas,
               strip=False,
               upx=False,
               name='DDMonitor')

app = BUNDLE(coll,
         name='DDMonitor.app',
         icon='favicon.ico',
         bundle_identifier='com.github.zhimingshenjun.ddmonitor',
         info_plist={
            'NSAppleScriptEnabled': False,
            'NSPrincipalClass': 'NSApplication',
            'NSAppleScriptEnabled': False,
            'CFBundleDocumentTypes': [],
            'CFBundleName': 'DDMonitor'
            }
         )

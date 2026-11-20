# Third-party notices

Local PDF is distributed under the GNU Affero General Public License, version 3. The application's source and build script are included under `source` in the install directory. Windows fonts are loaded from the running PC and are subject to their individual licenses.

| Component | License and source |
| --- | --- |
| PyMuPDF 1.27.2.2 and MuPDF | GNU AGPL v3. [PyMuPDF source release](https://pypi.org/project/PyMuPDF/1.27.2.2/#files), [MuPDF source releases](https://mupdf.com/releases/). |
| Qt 6.11.1, PySide6 Essentials 6.11.1 and Shiboken6 6.11.1 | LGPL v3. [Qt source](https://download.qt.io/archive/qt/6.11/6.11.1/submodules/), [PySide6 and Shiboken6 source](https://code.qt.io/cgit/pyside/pyside-setup.git/tag/?h=v6.11.1), [Qt component notices](https://doc.qt.io/qt-6/licenses-used-in-qt.html), [Qt for Python notices](https://doc.qt.io/qtforpython-6/licenses.html). |
| fontTools 4.56.0 | MIT. [Source](https://github.com/fonttools/fonttools/tree/4.56.0). |
| CPython 3.13 | Python Software Foundation License. [Source releases](https://www.python.org/downloads/source/). |
| PyInstaller 6.12.0 bootloader | GNU GPL v2 or later, with the PyInstaller bootloader exception. [Source](https://github.com/pyinstaller/pyinstaller/tree/v6.12.0). |

The package uses separate Qt DLLs. You may replace them with compatible modified DLLs and reverse engineer the application to debug changes to the LGPL libraries. Copies of the license texts are included under `licenses`.

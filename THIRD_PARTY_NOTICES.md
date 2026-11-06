# Third-party notices

TextSnap redistributes the components below. Full license texts are in the
`licenses` folder next to this file in the packaged build (collected from
each package by `tools/collect_licenses.py`) and in `vendor/tesseract/licenses`.

## OCR engine (folder `vendor/tesseract`)

The Tesseract binaries are the official Windows build by Universität Mannheim
(UB Mannheim), version 5.4.0.20240606, redistributed **unmodified** (they keep
their original Authenticode signature). Only `tesseract.exe` and the DLLs it
loads are included; the training tools are not.

| Component | License | Source |
|---|---|---|
| Tesseract OCR 5.4.0 (`tesseract.exe`, `libtesseract-5.dll`) | Apache-2.0 | https://github.com/tesseract-ocr/tesseract, build: https://github.com/UB-Mannheim/tesseract |
| Trained models `tessdata_best` and `tessdata_fast` (`eng`, `heb`) | Apache-2.0 | https://github.com/tesseract-ocr/tessdata_best, https://github.com/tesseract-ocr/tessdata_fast |
| Leptonica (`libleptonica-6.dll`) | BSD-2-Clause style (Leptonica license) | http://www.leptonica.org |
| libarchive | BSD-2-Clause | https://www.libarchive.org |
| libb2 (BLAKE2) | CC0-1.0 / OpenSSL / Apache-2.0 (choice) | https://github.com/BLAKE2/libb2 |
| bzip2 | bzip2-1.0.6 license (BSD-style) | https://sourceware.org/bzip2 |
| OpenSSL libcrypto 3 | Apache-2.0 | https://www.openssl.org |
| libdeflate | MIT | https://github.com/ebiggers/libdeflate |
| Expat | MIT | https://libexpat.github.io |
| GCC runtime (`libgcc_s_seh-1.dll`, `libstdc++-6.dll`) | GPL-3.0 with GCC Runtime Library Exception | https://gcc.gnu.org |
| giflib | MIT | https://giflib.sourceforge.net |
| GNU libiconv | LGPL-2.1-or-later | https://www.gnu.org/software/libiconv |
| JBIG-KIT (`libjbig-0.dll`) | GPL-2.0-or-later | https://www.cl.cam.ac.uk/~mgk25/jbigkit/ |
| libjpeg-turbo | IJG / BSD-3-Clause / zlib | https://libjpeg-turbo.org |
| LERC | Apache-2.0 | https://github.com/Esri/lerc |
| LZ4 | BSD-2-Clause | https://github.com/lz4/lz4 |
| XZ Utils / liblzma | 0BSD / public domain | https://tukaani.org/xz |
| OpenJPEG | BSD-2-Clause | https://www.openjpeg.org |
| libpng | libpng license | http://www.libpng.org |
| libwebp / libsharpyuv | BSD-3-Clause | https://chromium.googlesource.com/webm/libwebp |
| LibTIFF | libtiff license (BSD-style) | https://libtiff.gitlab.io/libtiff |
| mingw-w64 winpthreads | MIT / BSD-style | https://www.mingw-w64.org |
| Zstandard | BSD-3-Clause (or GPL-2.0) | https://github.com/facebook/zstd |
| zlib | zlib license | https://zlib.net |

The GPL/LGPL-licensed DLLs above (JBIG-KIT, libiconv) are used only by the
separate `tesseract.exe` process, are shipped unmodified, and their complete
source code is available from the projects listed and from the MSYS2 package
repository (https://packages.msys2.org) that the UB Mannheim build uses.
GPL-2.0, GPL-3.0, LGPL-2.1 and LGPL-3.0 texts are included in `licenses`.

## Application runtime

| Component | License | Source |
|---|---|---|
| Python 3.14 | PSF License | https://www.python.org |
| Qt 6 and PySide6 / Shiboken6 (Qt for Python) | LGPL-3.0 (dynamically linked; the Qt DLLs can be replaced) | https://www.qt.io, https://code.qt.io |
| NumPy (with bundled OpenBLAS etc.) | BSD-3-Clause (see bundled notices) | https://numpy.org |
| Pillow | MIT-CMU (HPND) | https://python-pillow.org |
| pypdfium2 and PDFium | Apache-2.0 / BSD-3-Clause | https://github.com/pypdfium2-team/pypdfium2, https://pdfium.googlesource.com |
| zxing-cpp | Apache-2.0 | https://github.com/zxing-cpp/zxing-cpp |
| PyInstaller bootloader | GPL-2.0 with bootloader exception | https://pyinstaller.org |

TextSnap itself does not contact any of these projects or any other server.

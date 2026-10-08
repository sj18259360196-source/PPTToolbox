# Third-party components

The root MIT license covers original PPTToolbox code. It does not relicense
third-party software, icons, medical artwork, fonts, or user project material.

The Windows distribution contains CPython and packages pinned by
`distribution/runtime-lock.json` and `distribution/requirements-release.lock`.
`DEPENDENCIES.json` lists the installed distribution names and versions.
The runtime retains Python's license and each wheel's original license/notice
files, including PDFium's third-party notices. PyMuPDF is not bundled in the
public distribution. PDF rasterization uses pypdfium2/PDFium.

Key license families include Python's PSF license, NumPy/SciPy's BSD licenses,
python-pptx's MIT license, Pillow's MIT-CMU license, pythonnet's MIT license,
and cryptography's Apache-2.0 or BSD-3-Clause license. Shapely wheels include
GEOS, which retains its LGPL-2.1-or-later terms. Upstream source and build
instructions are available from the Shapely and GEOS projects. The DLL remains
separately replaceable; replacing it can invalidate the application's integrity
checks, so custom distributions must rebuild their manifests. Pystray retains
its LGPL-3.0 license and is installed as replaceable Python source modules.
The matching GEOS, Shapely, pystray and proxy_tools source distributions accompany
the release in the third-party sources archive. This does not
restrict rights granted by GEOS's license.

Icon and artwork attribution is maintained in
`assets/icon-packs/THIRD_PARTY.md`, the adjacent `licenses` directory, and each
catalog's per-item source records. CC BY artwork still requires attribution in
the resulting work. Do not assume the application's MIT license covers artwork.

The Inno Setup language file and its license/source record are retained under
`distribution/languages`. Microsoft Edge WebView2, .NET Framework, PowerPoint,
and optional LibreOffice are external prerequisites, not copied from the author's
computer into this installer. No personal fonts or paid font files are bundled.

Upstream projects

- https://www.python.org/psf/license/
- https://github.com/pypdfium2-team/pypdfium2
- https://pdfium.googlesource.com/pdfium/
- https://github.com/shapely/shapely
- https://libgeos.org/
- https://github.com/pyca/cryptography
- https://github.com/r0x0r/pywebview
- https://github.com/pythonnet/pythonnet

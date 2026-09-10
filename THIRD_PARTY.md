# Third-party components

- React — MIT — https://github.com/facebook/react
- FastAPI — MIT — https://github.com/fastapi/fastapi
- Uvicorn — BSD-3-Clause — https://github.com/encode/uvicorn
- HTTPX — BSD-3-Clause — https://github.com/encode/httpx
- Pydantic — MIT — https://github.com/pydantic/pydantic
- pypdf — BSD-3-Clause — https://github.com/py-pdf/pypdf
- PDF.js (`pdfjs-dist`) — Apache-2.0 — https://github.com/mozilla/pdf.js
- Lucide — ISC — https://github.com/lucide-icons/lucide
- Vite — MIT — https://github.com/vitejs/vite
- Electron (desktop runtime) — MIT; Chromium and bundled components retain their own notices — https://github.com/electron/electron
- PyInstaller (desktop build tool) — GPL-2.0-or-later with bootloader exception permitting distributed applications — https://pyinstaller.org/
- Python (bundled desktop engine) — PSF License — https://www.python.org/
- Tectonic (bundled desktop / external compiler) — MIT — https://github.com/tectonic-typesetting/tectonic
- Fandol fonts (downloaded by compiler bundle) — GPL with font exception — https://ctan.org/pkg/fandol
- Noto Serif CJK SC Regular (bundled fallback font) — SIL Open Font License 1.1 — https://github.com/notofonts/noto-cjk ; license retained in `app/resources/fonts/LICENSE`.
- OpenCC Python reimplementation — Apache-2.0 — https://github.com/yichen0831/opencc-python ; used to normalize generated Chinese prose to the selected writing system.
- Adobe-GB1-UCS2 CMap, version 9.000, Copyright 1990–2020 Adobe. BSD-style license is retained in full at the top of `app/resources/cmaps/Adobe-GB1-UCS2`. Source project: https://github.com/adobe-type-tools/mapping-resources-pdf . The file was sourced from the bundled Poppler data distribution, unchanged.

Runtime package versions are locked by `uv.lock` and `frontend/package-lock.json`. PDF.js CMaps, standard fonts and WASM files are copied from its installed distribution into the local build, so reading does not depend on a CDN.

The frontend build retains full React, React DOM, Scheduler, Lucide and PDF.js license texts in `THIRD_PARTY_LICENSES.txt`, served with the web UI and included in the wheel. PDF.js font, CMap and WASM licenses are retained in their respective resource directories.

README reader screenshots show excerpts of the original text and a TeXGlot-generated Chinese translation from *Attention Is All You Need*, Ashish Vaswani et al., NeurIPS 2017, [arXiv:1706.03762v7](https://arxiv.org/abs/1706.03762v7). The screenshots illustrate corresponding prose and experiment tables; the machine translation is not an official translation of the paper. The walkthrough and default example fetch the paper from arXiv at run time; the full paper and source are not bundled. Research papers are not relicensed under Apache 2.0.

Desktop versions are locked in `desktop/package-lock.json`. Desktop packages retain Python and dependency notices in `THIRD_PARTY_NOTICES.txt`, the compiler license, and `LICENSES.chromium.html` extracted from the checksum-verified Electron distribution. The app Help menu opens these notices. PyInstaller is used under its bootloader exception; the TeXGlot application remains Apache-2.0.

Ghostscript is an optional, separately installed EPS-to-PDF command-line converter (GNU AGPL / commercial licensing). TeXGlot does not bundle it or link to its libraries. Upstream: https://www.ghostscript.com/ .

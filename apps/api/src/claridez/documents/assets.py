from __future__ import annotations

import hashlib

WORDMARK = b"""<svg xmlns="http://www.w3.org/2000/svg" width="150" height="38">
<rect width="150" height="38" rx="4" fill="#123047"/>
<text x="14" y="25" font-family="DejaVu Sans" font-size="16" fill="#ffffff">CLARIDEZ</text>
</svg>"""

DOCUMENT_CSS = """
@page { size: A4; margin: 18mm 17mm 20mm; @bottom-right {
  content: "Página " counter(page) " de " counter(pages); font-size: 8pt; color: #52636e;
} }
body { font-family: "DejaVu Sans", sans-serif; font-size: 10pt; line-height: 1.45;
  color: #172630; }
h1 { color: #123047; font-size: 20pt; margin: 12mm 0 6mm; }
h2 { color: #123047; font-size: 14pt; margin-top: 8mm; }
p, li { orphans: 3; widows: 3; }
table { width: 100%; border-collapse: collapse; margin: 6mm 0; }
thead { display: table-header-group; }
tr { break-inside: avoid; }
th, td { border: 0.25mm solid #84939c; padding: 2.2mm; text-align: left; }
th { background: #e9f0f3; color: #123047; }
.document-header { display: flex; justify-content: space-between; align-items: center;
  border-bottom: 0.6mm solid #123047; padding-bottom: 4mm; }
.preview-watermark { position: fixed; top: 42%; left: 10%; transform: rotate(-32deg);
  color: rgba(140, 30, 30, .18); font-size: 54pt; font-weight: bold; z-index: 20; }
"""


def render_assets_manifest() -> dict[str, object]:
    return {
        "version": "claridez-render-assets-v1",
        "wordmark_sha256": hashlib.sha256(WORDMARK).hexdigest(),
        "stylesheet_sha256": hashlib.sha256(DOCUMENT_CSS.encode()).hexdigest(),
        "fonts": ["DejaVu Sans 2.37-6"],
    }

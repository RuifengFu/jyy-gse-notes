"""Render a markdown note (with relative images) to PDF, same style as voice-summary.

    python render_pdf.py note.md [out.pdf]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / "project/VideoSummary"))
from export_notes import render_pdf  # noqa: E402  pandoc → HTML → headless Chrome

md = Path(sys.argv[1]).resolve()
render_pdf(md, Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else md.with_suffix(".pdf"))
print(md.with_suffix(".pdf") if len(sys.argv) < 3 else sys.argv[2])

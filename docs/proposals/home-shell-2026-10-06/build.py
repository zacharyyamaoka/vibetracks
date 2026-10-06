#!/usr/bin/env python3
"""Build the self-contained proposals report (index.html) and the app-only page (app.html) the recorder drives.

    python3 /home/bam/vibetracks/reports/media/vibetracks-home-proposals-2026-10-06/build.py

{{media:NAME}} in src/report.html becomes a data: URI of media/NAME (missing files become an empty string and are
listed on stderr), /*PROTO_CSS*/ and /*PROTO_JS*/ inline the shared prototype, /*SPEC_JSON*/ inlines src/spec.json.
"""
import base64
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
SRC, MEDIA = HERE / "src", HERE / "media"
MIME = {".webp": "image/webp", ".png": "image/png", ".jpg": "image/jpeg", ".gif": "image/gif", ".webm": "video/webm", ".mp4": "video/mp4"}

css = (SRC / "proto.css").read_text()
js = (SRC / "proto.js").read_text().replace("/*ZEN*/", (SRC / "zen.js").read_text())

MEDIA_RE = re.compile(r"\{\{media:([\w.\-]+)\}\}")


def media_uri(name: str) -> str:
    path = MEDIA / name
    if not path.exists():
        print("missing media:", name, file=sys.stderr)
        return ""
    return f"data:{MIME[path.suffix]};base64," + base64.b64encode(path.read_bytes()).decode()


js = MEDIA_RE.sub(lambda m: media_uri(m.group(1)), js)
# {{file:NAME}} -> a relative link to media/NAME (history rounds load their stills from the folder, not inlined)
FILE_RE = re.compile(r"\{\{file:([\w.\-]+)\}\}")
app = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vibe Tracks shell prototype</title><style>html,body{{margin:0;height:100%;background:#fff}}{css}</style></head>
<body><div id="app" style="height:100vh"></div><script>{js}
VTP.mount(document.getElementById('app'), {{standalone: true, rec: /rec=1/.test(location.search)}});</script></body></html>"""
(HERE / "app.html").write_text(app)

missing = []


def media(match: re.Match) -> str:
    path = MEDIA / match.group(1)
    if not path.exists():
        missing.append(path.name)
        return ""
    return f"data:{MIME[path.suffix]};base64," + base64.b64encode(path.read_bytes()).decode()


report = (SRC / "report.html").read_text()
spec = json.loads((SRC / "spec.json").read_text())
report = report.replace("/*PROTO_CSS*/", css).replace("/*PROTO_JS*/", js).replace("/*SPEC_JSON*/", json.dumps(spec, ensure_ascii=False))
proof = MEDIA / "proof.json"
report = report.replace("/*PROOF_JSON*/", proof.read_text() if proof.exists() else "null")
r3p = MEDIA / "r3-proof.json"
report = report.replace("/*R3PROOF_JSON*/", r3p.read_text() if r3p.exists() else "null")
r2p = MEDIA / "r2-proof.json"
report = report.replace("/*R2PROOF_JSON*/", r2p.read_text() if r2p.exists() else "null")
report = re.sub(r"\{\{media:([\w.\-]+)\}\}", media, report)
report = FILE_RE.sub(lambda m: "media/" + m.group(1) if (MEDIA / m.group(1)).exists() else missing.append(m.group(1)) or "", report)
out = HERE / "index.html"
out.write_text(report)
print(f"{out}  {out.stat().st_size / 1e6:.2f} MB")
if missing:
    print("missing media:", ", ".join(sorted(set(missing))), file=sys.stderr)

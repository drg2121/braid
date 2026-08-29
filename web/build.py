#!/usr/bin/env python3
"""Bundle the web app into one self-contained HTML file.

The multi-file version in this folder is what GitHub Pages serves. The bundle
this produces is a single file that can be emailed, AirDropped or kept in
Files, and it works with no network at all -- useful for handing to someone who
will never visit a web page to get it.
"""

from __future__ import annotations

import argparse
import base64
import re
from pathlib import Path

HERE = Path(__file__).parent

# Module order matters: each may only import from ones already inlined.
MODULES = ["wal.js", "jwlibrary.js", "merge.js", "verify.js", "store.js", "app.js"]


def strip_module_syntax(source: str, name: str) -> str:
    """Turn an ES module into plain script text.

    Every module ends up in one scope, so imports become unnecessary and
    exports would be syntax errors outside a module.
    """
    # Drop import statements; the names they bind are already in scope.
    source = re.sub(
        r"^import\s+(?:[\w*{}\n\r\t, ]+from\s+)?[\"'][^\"']+[\"'];?\s*$",
        "",
        source,
        flags=re.MULTILINE,
    )
    source = re.sub(
        r"^import\s*\{[^}]*\}\s*from\s*[\"'][^\"']+[\"'];?\s*$",
        "",
        source,
        flags=re.MULTILINE | re.DOTALL,
    )
    # `export { a, b };` re-exports nothing useful once everything shares a scope.
    source = re.sub(r"^export\s*\{[^}]*\};?\s*$", "", source, flags=re.MULTILINE)
    # `export const`, `export function`, `export class` keep their declarations.
    source = re.sub(r"^export\s+(?=(const|let|var|function|class|async))", "", source,
                    flags=re.MULTILINE)
    return f"// ---- {name} ----\n{source.strip()}\n"


TOP_LEVEL = re.compile(
    r"^(?:const|let|var|function|async function|class)\s+([A-Za-z_$][\w$]*)",
    re.MULTILINE,
)


def check_for_collisions(pieces: dict[str, str]) -> None:
    """Refuse to build if two modules declare the same top-level name.

    Bundling drops every module into one scope, where two modules that each
    define, say, ``DB_NAME`` become a SyntaxError that only shows up in the
    browser console -- with the whole page dead and nothing else to go on.
    """
    seen: dict[str, str] = {}
    clashes: list[str] = []
    for name, source in pieces.items():
        for match in TOP_LEVEL.finditer(source):
            declared = match.group(1)
            if declared in seen and seen[declared] != name:
                clashes.append(f"{declared} (in {seen[declared]} and {name})")
            seen.setdefault(declared, name)
    if clashes:
        raise SystemExit(
            "cannot bundle: these names are declared in more than one module, "
            "and every module shares one scope once bundled.\n  "
            + "\n  ".join(sorted(set(clashes)))
            + "\nRename one of each pair."
        )


def build(out_path: Path) -> Path:
    html = (HERE / "index.html").read_text(encoding="utf-8")
    sql_js = (HERE / "vendor" / "sql-wasm.js").read_text(encoding="utf-8")
    wasm = (HERE / "vendor" / "sql-wasm.wasm").read_bytes()

    pieces = {
        name: strip_module_syntax((HERE / name).read_text(encoding="utf-8"), name)
        for name in MODULES
    }
    check_for_collisions(pieces)
    bundle = "\n".join(pieces.values())

    replacement = (
        "<script>\n"
        f"window.JWSYNC_WASM_BASE64 = \"{base64.b64encode(wasm).decode('ascii')}\";\n"
        "</script>\n"
        "<script>\n"
        f"{sql_js}\n"
        "</script>\n"
        "<script>\n"
        "(async () => {\n"
        f"{bundle}\n"
        "})();\n"
        "</script>"
    )

    marker_start = html.index("<!-- sql.js ships")
    marker_end = html.index("</body>", marker_start)
    html = html[:marker_start] + replacement + "\n" + html[marker_end:]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=HERE.parent / "dist" / "jwsync.html",
        help="where to write the bundle",
    )
    args = parser.parse_args()
    out = build(args.output)
    size = out.stat().st_size
    print(f"wrote {out} ({size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

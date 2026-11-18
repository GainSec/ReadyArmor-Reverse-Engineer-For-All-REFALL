#!/usr/bin/env python3
"""Build the repository's offline technical atlas with the Python standard library."""

from __future__ import annotations
import argparse, ast, base64, hashlib, html, json, re, textwrap
from pathlib import Path
from urllib.parse import unquote, urlsplit


def esc(value):
    return html.escape(str(value), quote=True)


def esc_code(value):
    """Preserve source whitespace as HTML entities at display-line endings."""
    return re.sub(
        r"[ \t]+(?=\n|$)",
        lambda match: "".join(
            "&#32;" if char == " " else "&#9;" for char in match.group()
        ),
        esc(value),
    )


def slug(value):
    value = re.sub(r"[`*_]", "", str(value)).lower()
    return (
        re.sub(r"-+", "-", re.sub(r"[^\w\s-]", "", value).strip().replace(" ", "-"))
        or "section"
    )


def contrast_color(value, background):
    value = value.lstrip("#")
    rgb = (
        [int(value[i : i + 2], 16) for i in (0, 2, 4)]
        if len(value) == 6
        else [130, 180, 170]
    )

    def luminance(c):
        vals = [x / 255 for x in c]
        vals = [
            x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in vals
        ]
        return 0.2126 * vals[0] + 0.7152 * vals[1] + 0.0722 * vals[2]

    bg = [int(background[i : i + 2], 16) for i in (1, 3, 5)]
    target = 255 if luminance(bg) < 0.5 else 0
    for _ in range(80):
        a, b = sorted([luminance(rgb), luminance(bg)])
        if (b + 0.05) / (a + 0.05) >= 4.8:
            break
        rgb = [round(x * 0.96 + target * 0.04) for x in rgb]
    return "#" + "".join(f"{x:02x}" for x in rgb)


def json_text(value):
    return (
        json.dumps(value, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def fences_removed(text):
    lines = []
    fence = None
    for line in text.splitlines():
        m = re.match(r"^\s*(`{3,}|~{3,})", line)
        if fence:
            if m and m[1][0] == fence[0] and len(m[1]) >= len(fence):
                fence = None
            continue
        if m:
            fence = m[1]
            continue
        lines.append(line)
    return "\n".join(lines)


def update_source_index(root, areas):
    groups = {}
    total = 0
    extensions = {".py", ".js", ".mjs", ".ts", ".svelte", ".c", ".h", ".sh"}
    for area in areas:
        p = (root / area).resolve()
        if not p.is_relative_to(root):
            raise ValueError("Source index leaves repository: " + area)
        paths = [p] if p.is_file() else sorted(p.rglob("*")) if p.is_dir() else []
        rows = []
        for file in paths:
            if not file.is_file() or (
                file.suffix not in extensions and area not in ["bin", "toolchain/bin"]
            ):
                continue
            if any(
                v in file.relative_to(root).parts
                for v in ["tests", "__pycache__", "vendor", "node_modules", "harness"]
            ):
                continue
            if file.name.startswith("test_") or file.name.endswith(".test.ts"):
                continue
            text = file.read_text(errors="replace")
            definitions = []
            if file.suffix == ".py":
                try:
                    for node in ast.parse(text).body:
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            definitions.append(node.name)
                        if isinstance(node, ast.ClassDef):
                            definitions.append(node.name)
                            definitions.extend(
                                node.name + "." + child.name
                                for child in node.body
                                if isinstance(
                                    child, (ast.FunctionDef, ast.AsyncFunctionDef)
                                )
                            )
                except SyntaxError:
                    pass
            else:
                for line in text.splitlines():
                    match = re.search(
                        r"(?:export\s+)?(?:async\s+)?function\s+([\w$]+)|(?:export\s+)?class\s+(\w+)|^(\w+)\s*\(\)\s*\{",
                        line,
                    )
                    if match:
                        definitions.append(
                            next(value for value in match.groups() if value)
                        )
            relative = file.relative_to(root).as_posix()
            fragment = "#L1" if text.splitlines() else ""
            selected = ", ".join("`" + name + "`" for name in definitions[:12]) or (
                "Module declarations or executable statements"
                if text.strip()
                else "Empty module marker"
            )
            if len(definitions) > 12:
                selected += f"; {len(definitions) - 12} additional definitions"
            rows.append(
                f"| [{relative}](../{relative}{fragment}) | {len(text.splitlines())} | {len(definitions)} | {selected} |"
            )
            total += 1
        if rows:
            groups[area] = rows
    text = [
        "# Source file index\n",
        "This index locates the first-party implementation files behind the product.\n",
        "It groups files by source directory and lists selected declared interfaces.\n",
        "The table gives line totals, declaration counts, and selected interface names.\n",
        f"The index contains {total} implementation files.\n",
        "Python definition counts include module functions, classes, and their declared methods.\n",
        "Other file types list explicit function and class declarations where available.\n",
        "The interface column shows up to twelve definitions for each file.\n",
    ]
    for area, rows in groups.items():
        text += [
            "\n## " + area + "\n",
            "| File | Lines | Definitions | Selected interfaces |",
            "| --- | --- | --- | --- |",
        ] + rows
    text += [
        "\n## Read a source location\n",
        "1. Select a file from the relevant subsystem.",
        "2. Read its imports, declarations, and named interfaces.",
        "3. Use the architecture and workflow guides to identify its callers and stored records.",
        "4. Compare an observed result with the relevant decision and state change.\n",
    ]
    (root / "docs/source-index.md").write_text("\n".join(text) + "\n")


class Atlas:
    def __init__(self, root):
        self.root = root.resolve()
        self.profile = json.loads((root / "docs/site.json").read_text())
        self.images = {}
        self.sources = {}
        self.search = []
        self.chapter_map = {}
        self.chapters = []
        if self.profile.get("sourceRoots"):
            update_source_index(self.root, self.profile["sourceRoots"])
        queue = list(self.profile["chapters"])
        seen = set()
        while queue:
            ch = queue.pop(0)
            path = ch["path"]
            if path in seen:
                continue
            seen.add(path)
            p = self.safe_file(path)
            if not p.is_file():
                raise ValueError("Missing chapter: " + path)
            content = p.read_text()
            item = dict(
                ch, text=content, id="chapter-" + slug(path.removesuffix(".md"))
            )
            self.chapters.append(item)
            self.chapter_map[path] = item
            for target in re.findall(r"(?<!!)\[[^\]]+\]\(([^\s)]+)\)", content):
                if urlsplit(target).scheme or target.startswith("#"):
                    continue
                ref = (p.parent / unquote(target.split("#")[0])).resolve()
                if (
                    ref.suffix != ".md"
                    or not ref.is_file()
                    or not ref.is_relative_to(self.root)
                ):
                    continue
                rel = ref.relative_to(self.root).as_posix()
                if any(
                    x in rel for x in ["/seed/", "/layer2-templates/", "/vendor/"]
                ) or ref.name in ["AGENTS.md", "CODEX.md", "CLAUDE.md"]:
                    continue
                queue.append(
                    {"path": rel, "label": ref.stem.replace("-", " ").replace("_", " ")}
                )
        for ch in self.chapters:
            counts = {}
            heads = {}
            for m in re.finditer(
                r"^#{1,6}\s+(.+?)\s*#*$", fences_removed(ch["text"]), re.M
            ):
                key = slug(m[1])
                n = counts.get(key, 0)
                counts[key] = n + 1
                original = key + (f"-{n}" if n else "")
                heads[original] = ch["id"] + "-" + original
            ch["heads"] = heads

    def safe_file(self, path):
        p = (self.root / path).resolve()
        if not p.is_relative_to(self.root):
            raise ValueError("Reference leaves repository: " + str(path))
        return p

    def source(self, ref):
        if isinstance(ref, str):
            ref = {"path": ref, "line": 1, "symbol": ""}
        path = ref.get("path", ref.get("file", ""))
        p = self.safe_file(path)
        if not p.is_file():
            raise ValueError("Missing source reference: " + path)
        n = ref.get("line", ref.get("start_line", 1))
        m = re.search(r"\d+", str(n))
        line = int(m[0]) if m else 1
        lines = p.read_text(errors="replace").splitlines()
        line = max(1, min(line, len(lines))) if lines else 0
        symbol = ref.get("symbol", "")
        requested_end = ref.get("endLine", ref.get("end_line"))
        selected_end = (
            min(len(lines), max(line, int(requested_end)))
            if requested_end is not None and lines
            else None
        )
        key = (
            "source-"
            + hashlib.sha256(
                f"{path}:{line}:{symbol}:{selected_end}".encode()
            ).hexdigest()[:12]
        )
        if key not in self.sources:
            lo = max(1, line - 4)
            hi = (
                selected_end if selected_end is not None else min(len(lines), line + 15)
            )
            excerpt = (
                "\n".join(f"{i:>5}  {lines[i - 1]}" for i in range(lo, hi + 1))
                if lines
                else "(Empty file)"
            )
            self.sources[key] = {
                "id": key,
                "path": path,
                "line": line,
                "endLine": selected_end,
                "symbol": symbol,
                "excerpt": excerpt,
            }
        return key

    def source_links(self, refs):
        if not refs:
            return ""
        if isinstance(refs, dict):
            refs = [refs]
        links = []
        for ref in refs:
            key = self.source(ref)
            r = self.sources[key]
            label = r["symbol"] or Path(r["path"]).name
            location = "L" + str(r["line"]) if r["line"] else "empty"
            if r.get("endLine") is not None and r["endLine"] > r["line"]:
                location += "–" + str(r["endLine"])
            links.append(
                f'<a class="source-link" href="#{key}" data-source="{key}"><span aria-hidden="true">↗</span> {esc(label)} <small>{location}</small></a>'
            )
        return '<div class="source-links">' + "".join(links) + "</div>"

    def link(self, label, target, ch):
        target = unquote(target.strip("<>"))
        if target.startswith(("https://", "http://", "mailto:")):
            return (
                f'<a href="{esc(target)}" rel="noreferrer">{self.inline(label, ch)}</a>'
            )
        if target.startswith("#"):
            dest = ch["heads"].get(target[1:], ch["id"])
            return f'<a href="#{dest}">{self.inline(label, ch)}</a>'
        path, _, fragment = target.partition("#")
        if urlsplit(path).scheme:
            return self.inline(label, ch)
        p = (self.root / ch["path"]).parent / path
        p = p.resolve()
        if not p.is_relative_to(self.root):
            return self.inline(label, ch)
        rel = p.relative_to(self.root).as_posix()
        if rel in self.chapter_map:
            dest = self.chapter_map[rel]
            anchor = dest["heads"].get(fragment, dest["id"])
            return f'<a href="#{anchor}">{self.inline(label, ch)}</a>'
        if rel == "docs/index.html":
            return f'<a href="#overview">{self.inline(label, ch)}</a>'
        if p.is_file() and p.suffix in [
            ".py",
            ".ts",
            ".js",
            ".mjs",
            ".c",
            ".h",
            ".sh",
            ".json",
            ".toml",
            ".md",
            ".yaml",
            ".yml",
        ]:
            m = re.search(r"\d+", fragment)
            ref = {"path": rel, "line": int(m[0]) if m else 1}
            key = self.source(ref)
            return f'<a href="#{key}" data-source="{key}">{self.inline(label, ch)}</a>'
        return self.inline(label, ch)

    def image_data(self, path):
        """Embed the original raster bytes; never load publication assets by URL."""
        if path not in self.images:
            file = self.safe_file(path)
            mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}.get(file.suffix.lower())
            if not mime or not file.is_file():
                raise ValueError("Missing or unsupported screenshot: " + path)
            self.images[path] = "data:" + mime + ";base64," + base64.b64encode(file.read_bytes()).decode("ascii")
        return self.images[path]

    def image_markup(self, alt, target, ch):
        target = unquote(target.strip("<>"))
        if urlsplit(target).scheme or target.startswith("//"):
            raise ValueError("Screenshot must be a repository raster image: " + target)
        file = (self.root / ch["path"]).parent / target
        file = self.safe_file(file)
        path = file.relative_to(self.root).as_posix()
        # Gallery images carry their original bytes once. Repeated chapter
        # images reuse that embedded resource when the interactive atlas starts.
        gallery_paths = {shot["path"] for shot in self.profile.get("screenshots", [])}
        asset = (
            f'data-image-ref="{esc(path)}"'
            if path in gallery_paths
            else f'src="{self.image_data(path)}"'
        )
        return (
            f'<span class="screenshot-inline"><button type="button" class="screenshot-open" data-screenshot="{esc(path)}" aria-label="{esc("Open full image: " + alt)}">'
            f'<img class="screenshot-preview" {asset} alt="{esc(alt)}" loading="lazy" decoding="async">'
            '<span class="screenshot-action">Open full image ↗</span></button></span>'
        )

    def render_screenshots(self):
        cards = []
        categories = {}
        for index, shot in enumerate(self.profile.get("screenshots", [])):
            path = shot["path"]
            title, alt, caption = shot["title"], shot["alt"], shot["caption"]
            src = self.image_data(path)
            ident = "screenshot-" + slug(path)
            kind = "ARCHITECTURE" if shot.get("kind") == "architecture" else "INTERFACE"
            category = shot.get("category", kind.title())
            categories.setdefault(category, {"href": ident, "count": 0})["count"] += 1
            cards.append(
                f'<figure class="screenshot-card" data-image-kind="{kind.lower()}" id="{ident}"><button type="button" class="screenshot-open" data-screenshot="{esc(path)}" aria-label="{esc("Open full image: " + title)}">'
                f'<img class="screenshot-preview" src="{src}" alt="{esc(alt)}" loading="lazy" decoding="async">'
                '<span class="screenshot-action">Open full image ↗</span></button>'
                f'<figcaption><span class="eyebrow">{index + 1:02} / {esc(kind)}</span><h3>{esc(title)}</h3><p>{esc(caption)}</p></figcaption></figure>'
            )
            self.search.append({"title": title, "chapter": "Screenshots", "href": "#" + ident, "text": alt + " " + caption})
        if not cards:
            return ""
        directory = (
            '<nav class="screenshot-directory" aria-label="Browse product views">'
            + "".join(
                f'<a href="#{item["href"]}">{esc(category)} <small>{item["count"]:02}</small></a>'
                for category, item in categories.items()
            )
            + '</nav>'
        )
        return (
            '<section class="section" id="screenshots"><div class="section-heading"><span class="eyebrow">PRODUCT VIEWS</span>'
            f'<h2>See the workspace.</h2><p>Explore {len(cards)} product {"view" if len(cards) == 1 else "views"}. Select a view to inspect the full image. Use the arrow keys to move between views.</p></div>'
            + directory + '<div class="screenshot-grid">' + "".join(cards) + '</div></section>'
        )

    def inline(self, value, ch):
        tokens = {}

        def token(markup):
            key = "ATLASTOKEN" + str(len(tokens)) + "END"
            tokens[key] = markup
            return key

        value = re.sub(
            r"`([^`]+)`", lambda m: token("<code>" + esc(m[1]) + "</code>"), str(value)
        )
        value = re.sub(
            r"!\[([^\]]*)\]\(([^)]+)\)",
            lambda m: token(self.image_markup(m[1], m[2], ch)),
            value,
        )
        value = re.sub(
            r"\[([^\]]+)\]\(([^)]+)\)",
            lambda m: token(self.link(m[1], m[2], ch)),
            value,
        )
        value = esc(value)
        value = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", value)
        value = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", value)
        for key, markup in tokens.items():
            value = value.replace(key, markup)
        return value

    def flow_svg(self, nodes, edges, ident, caption="System relationships"):
        if not nodes:
            return ""
        groups = {}
        for n in nodes:
            groups.setdefault(str(n.get("layer", "System")), []).append(n)
        width = 1000
        positions = {}
        rows = []
        rownum = 0
        for layer, items in groups.items():
            for offset in range(0, len(items), 4):
                row = items[offset : offset + 4]
                rows.append((layer, rownum))
                step = width / len(row)
                for col, n in enumerate(row):
                    positions[n["id"]] = (
                        col * step + 16,
                        rownum * 160 + 48,
                        step - 32,
                        92,
                        n,
                    )
                rownum += 1
        height = rownum * 160 + 10
        view_width = width + 40 if any(e.get("feedback") for e in edges) else width
        parts = [
            f'<figure class="diagram"><div class="diagram-scroll"><svg viewBox="0 0 {view_width} {height}" role="img" aria-label="{esc(caption)}" class="system-svg"><defs><marker id="arrow-{ident}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0 10 5 0 10z" fill="currentColor"/></marker></defs>'
        ]
        for layer, row in rows:
            parts.append(
                f'<text class="layer-label" x="18" y="{row * 160 + 25}">{esc(layer.upper())}</text>'
            )
        for e in edges:
            if e.get("from") not in positions or e.get("to") not in positions:
                continue
            x, y, w, h, _ = positions[e["from"]]
            xx, yy, ww, hh, _ = positions[e["to"]]
            if yy > y:
                ax, ay, bx, by = x + w / 2, y + h, xx + ww / 2, yy
            elif yy < y:
                ax, ay, bx, by = x + w, y + h / 2, xx + ww, yy + hh / 2
            else:
                ax, ay, bx, by = x + w, y + h / 2, xx, yy + hh / 2
            mid = (ay + by) / 2
            path = f"M {ax} {ay} C {ax} {mid} {bx} {mid} {bx} {by}"
            edge_class = "graph-edge"
            if e.get("feedback"):
                ax, ay, bx, by = x + w, y + h / 2, xx + ww, yy + hh / 2
                gutter = width + 22
                path = f"M {ax} {ay} H {gutter} V {by} H {bx}"
                edge_class += " feedback-edge"
            parts.append(
                f'<g class="{edge_class}" data-from="{esc(e["from"])}" data-to="{esc(e["to"])}"><path d="{path}" marker-end="url(#arrow-{ident})"/><title>{esc(e.get("label", ""))}</title></g>'
            )
        for i, (key, (x, y, w, h, n)) in enumerate(positions.items()):
            title = textwrap.wrap(n.get("title", key), max(12, int(w / 9)))[:2]
            role = textwrap.wrap(n.get("role", ""), max(14, int(w / 7)))[:2]
            parts.append(
                f'<g class="graph-node" data-node="{esc(key)}" role="button" tabindex="0" aria-label="{esc(n.get("title", key) + ": " + n.get("role", ""))}"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8"/><text class="node-index" x="{x + w - 15}" y="{y + 20}" text-anchor="end">{i + 1:02}</text>'
            )
            for j, line in enumerate(title):
                parts.append(
                    f'<text class="node-title" x="{x + 13}" y="{y + 25 + j * 19}">{esc(line)}</text>'
                )
            for j, line in enumerate(role):
                parts.append(
                    f'<text class="node-role" x="{x + 13}" y="{y + 63 + j * 15}">{esc(line)}</text>'
                )
            parts.append("</g>")
        parts.append(
            "</svg></div><figcaption>" + esc(caption) + "</figcaption></figure>"
        )
        return "".join(parts)

    def mermaid(self, code, ch, index):
        nodes = {}
        edges = []
        for line in code.splitlines():
            if line.strip().startswith(
                (
                    "flowchart",
                    "graph",
                    "%%",
                    "subgraph",
                    "end",
                    "direction",
                    "style",
                    "classDef",
                    "class ",
                )
            ):
                continue

            def node(m):
                key = m[1]
                label = (m[2] or m[3] or m[4] or key).strip('" ')
                nodes[key] = {"id": key, "title": label, "role": "", "layer": "Flow"}
                return key

            reduced = re.sub(
                r"([A-Za-z_][\w-]*)\s*(?:\[([^\]]+)\]|\{([^}]+)\}|\(([^)]+)\))",
                node,
                line,
            )
            for m in re.finditer(
                r"(?=([A-Za-z_][\w-]*)\s*(?:-->|-\.->|==>)\s*(?:\|([^|]+)\|\s*)?([A-Za-z_][\w-]*))",
                reduced,
            ):
                a, label, b = m.groups()
                nodes.setdefault(a, {"id": a, "title": a, "role": "", "layer": "Flow"})
                nodes.setdefault(b, {"id": b, "title": b, "role": "", "layer": "Flow"})
                edges.append({"from": a, "to": b, "label": label or ""})
        if not nodes:
            return "<pre><code>" + esc_code(code) + "</code></pre>"
        levels = {}
        incoming = {e["to"] for e in edges}
        roots = [n for n in nodes if n not in incoming] or [next(iter(nodes))]
        queue = [(n, 0) for n in roots]
        while queue:
            n, level = queue.pop(0)
            if n in levels:
                continue
            levels[n] = level
            for e in edges:
                if e["from"] == n and e["to"] not in levels:
                    queue.append((e["to"], level + 1))
        for i, n in enumerate(nodes.values()):
            n["layer"] = "Stage " + str(levels.get(n["id"], 0) + 1)
        return self.flow_svg(
            list(nodes.values()),
            edges,
            ch["id"] + "-flow-" + str(index),
            "Control and data flow",
        )

    def render_markdown(self, ch):
        lines = ch["text"].splitlines()
        out = []
        i = 0
        counts = {}
        listtag = None
        diagram = 0

        def close_list():
            nonlocal listtag
            if listtag:
                out.append("</" + listtag + ">")
                listtag = None

        while i < len(lines):
            line = lines[i]
            strip = line.strip()
            if not strip:
                close_list()
                i += 1
                continue
            fence = re.match(r"^\s*(`{3,}|~{3,})(.*)$", line)
            if fence:
                close_list()
                marker = fence[1]
                lang = fence[2].strip()
                body = []
                i += 1
                while i < len(lines):
                    if re.match(
                        r"^\s*"
                        + re.escape(marker[0])
                        + r"{"
                        + str(len(marker))
                        + r",}\s*$",
                        lines[i],
                    ):
                        break
                    body.append(lines[i])
                    i += 1
                code = "\n".join(body)
                i += 1
                if lang == "mermaid":
                    diagram += 1
                    out.append(self.mermaid(code, ch, diagram))
                else:
                    out.append(
                        '<div class="code-block"><div class="code-bar"><span>'
                        + esc(lang or "text")
                        + '</span><button class="copy-button" type="button">Copy</button></div><pre><code>'
                        + esc_code(code)
                        + "</code></pre></div>"
                    )
                continue
            heading = re.match(r"^(#{1,6})\s+(.+?)\s*#*$", line)
            if heading:
                close_list()
                level = min(6, len(heading[1]) + 1)
                title = heading[2]
                key = slug(title)
                n = counts.get(key, 0)
                counts[key] = n + 1
                key += f"-{n}" if n else ""
                anchor = ch["heads"][key]
                out.append(
                    f'<h{level} id="{anchor}">{self.inline(title, ch)}<a class="permalink" href="#{anchor}" aria-label="Link to {esc(title)}">#</a></h{level}>'
                )
                self.search.append(
                    {
                        "title": re.sub(r"[`*_]", "", title),
                        "chapter": ch["label"],
                        "href": "#" + anchor,
                        "text": " ".join(
                            lines[
                                i + 1 : next(
                                    (
                                        j
                                        for j in range(i + 1, len(lines))
                                        if re.match(r"^#{1,6}\s+", lines[j])
                                    ),
                                    len(lines),
                                )
                            ]
                        ),
                    }
                )
                i += 1
                continue
            if (
                strip.startswith("|")
                and i + 1 < len(lines)
                and re.match(r"^\s*\|?\s*:?-{3}", lines[i + 1])
            ):
                close_list()
                rows = []
                while i < len(lines) and lines[i].strip().startswith("|"):
                    rows.append(
                        [
                            c.strip()
                            for c in re.split(r"(?<!\\)\|", lines[i].strip().strip("|"))
                        ]
                    )
                    i += 1
                out.append(
                    '<div class="table-scroll"><table><thead><tr>'
                    + "".join("<th>" + self.inline(c, ch) + "</th>" for c in rows[0])
                    + "</tr></thead><tbody>"
                )
                for row in rows[2:]:
                    out.append(
                        "<tr>"
                        + "".join("<td>" + self.inline(c, ch) + "</td>" for c in row)
                        + "</tr>"
                    )
                out.append("</tbody></table></div>")
                continue
            if re.fullmatch(r"[-*_]{3,}", strip):
                close_list()
                out.append("<hr>")
                i += 1
                continue
            if strip.startswith(">"):
                close_list()
                block = []
                while i < len(lines) and lines[i].strip().startswith(">"):
                    block.append(lines[i].strip().lstrip(">").strip())
                    i += 1
                out.append(
                    "<blockquote>" + self.inline(" ".join(block), ch) + "</blockquote>"
                )
                continue
            item = re.match(r"^\s*(?:([-*+])\s+|(\d+)\.\s+)(.*)$", line)
            if item:
                tag = "ol" if item[2] else "ul"
                if listtag != tag:
                    close_list()
                    out.append("<" + tag + ">")
                    listtag = tag
                body = item[3]
                i += 1
                while (
                    i < len(lines)
                    and lines[i].startswith("  ")
                    and lines[i].strip()
                    and not re.match(r"^\s*(?:[-*+] |\d+\. |`{3,}|~{3,})", lines[i])
                ):
                    body += " " + lines[i].strip()
                    i += 1
                body = re.sub(r"^\[ \]\s*", "☐ ", body)
                body = re.sub(r"^\[[xX]\]\s*", "☑ ", body)
                out.append("<li>" + self.inline(body, ch) + "</li>")
                continue
            close_list()
            para = [strip]
            i += 1
            while (
                i < len(lines)
                and lines[i].strip()
                and not re.match(
                    r"^\s*(?:#{1,6} |[-*+] |\d+\. |`{3,}|~{3,}|\||>)", lines[i]
                )
            ):
                para.append(lines[i].strip())
                i += 1
            out.append("<p>" + self.inline(" ".join(para), ch) + "</p>")
        close_list()
        return "\n".join(out)

    def render_control_layers(self):
        layers = self.profile.get("controlLayers", [])
        if not layers:
            return ""
        tabs = []
        panels = []
        for index, layer in enumerate(layers):
            ident = "control-" + slug(layer["id"])
            title = layer["title"]
            kind = layer["kind"]
            tabs.append(
                f'<button type="button" role="tab" class="control-tab" id="tab-{ident}" data-control="{ident}" aria-controls="{ident}" aria-selected="{str(index == 0).lower()}" tabindex="{0 if index == 0 else -1}">'
                f'<span class="control-number">{index + 1:02}</span><span><strong>{esc(title)}</strong><small>{esc(kind)}</small></span></button>'
            )
            fields = "".join(
                '<div class="control-field"><dt>'
                + esc(label)
                + "</dt><dd>"
                + esc(layer[key])
                + "</dd></div>"
                for key, label in [
                    ("boundary", "Boundary"),
                    ("mechanism", "Implemented mechanism"),
                    ("prevents", "Decision or effect"),
                    ("activation", "Activation and coverage"),
                ]
            )
            panels.append(
                f'<article class="control-panel" role="tabpanel" tabindex="0" id="{ident}" aria-labelledby="tab-{ident}">'
                f'<div class="control-panel-heading"><span class="eyebrow">LAYER {index + 1:02}</span><span class="control-kind">{esc(kind)}</span></div><h3>{esc(title)}</h3>'
                '<dl class="control-fields">' + fields + "</dl>"
                '<div class="control-example"><h4>Code-path example</h4><div><span>INPUT</span><p>'
                + esc(layer["attempt"])
                + "</p></div><div><span>RESULT</span><p>"
                + esc(layer["decision"])
                + "</p></div></div>"
                + self.source_links(layer.get("source", []))
                + "</article>"
            )
            self.search.append(
                {
                    "title": title,
                    "chapter": "Control in Depth / " + kind,
                    "href": "#" + ident,
                    "text": " ".join(
                        str(layer[key])
                        for key in [
                            "boundary",
                            "mechanism",
                            "prevents",
                            "activation",
                            "attempt",
                            "decision",
                        ]
                    ),
                }
            )
        summary = self.profile.get(
            "controlSummary",
            "Examine the boundaries that control operations, task state, and accepted results.",
        )
        return (
            '<section class="section" id="control-in-depth"><div class="section-heading"><span class="eyebrow">READY ARMOR / CONTROL IN DEPTH</span>'
            "<h2>Build control from the boundary up.</h2><p>"
            + esc(summary)
            + "</p></div>"
            '<p class="control-order">Lowest implemented boundary first. Select a layer to inspect its checks, activation, and decision scope.</p>'
            '<div class="control-layout"><div class="control-rail" role="tablist" aria-label="Control layers, from the lowest boundary upward" aria-orientation="vertical">'
            + "".join(tabs)
            + '</div><div class="control-panels">'
            + "".join(panels)
            + "</div></div></section>"
        )

    def build(self):
        p = self.profile
        name = p["name"]
        product = p["product"]
        ch0 = self.chapters[0]
        cards = []
        for i, f in enumerate(p.get("features", [])):
            ident = "feature-" + slug(f["title"])
            description = f.get("description", "")
            mechanism = f.get("mechanism", "")
            cards.append(
                f'<article class="feature-card" id="{ident}"><span class="eyebrow">{i + 1:02} / CAPABILITY</span><h3>{esc(f["title"])}</h3><p>{esc(description)}</p><div class="mechanism">{esc(mechanism)}</div>{self.source_links(f.get("source", []))}</article>'
            )
            self.search.append(
                {
                    "title": f["title"],
                    "chapter": "Capabilities",
                    "href": "#" + ident,
                    "text": description + " " + mechanism,
                }
            )
        uses = "".join(
            '<article class="use-card"><h3>'
            + esc(u["title"])
            + "</h3><p>"
            + esc(u["description"])
            + '</p><div class="outcome">'
            + esc(u.get("outcome", ""))
            + "</div></article>"
            for u in p.get("useCases", [])
        )
        architecture = p.get("architecture", {})
        graph = self.flow_svg(
            architecture.get("nodes", []),
            architecture.get("edges", []),
            "architecture",
            "Select a component to examine its role and source entry points.",
        )
        node_content = {}
        for n in architecture.get("nodes", []):
            node_content[n["id"]] = {
                "title": n["title"],
                "role": n.get("role", ""),
                "sources": self.source_links(n.get("source", [])),
            }
        screenshots_html = self.render_screenshots()
        screenshot_nav = '<a href="#screenshots">Product gallery</a>' if screenshots_html else ""
        control_html = self.render_control_layers()
        control_nav = (
            '<a href="#control-in-depth">Control in Depth</a>' if control_html else ""
        )
        flows = []
        flow_nodes = {}
        tabs = []
        for n, f in enumerate(p.get("flows", [])):
            ident = "trace-" + slug(f.get("id", f["title"]))
            tabs.append(
                f'<button type="button" class="trace-tab" role="tab" id="tab-{ident}" aria-controls="{ident}" aria-selected="{str(n == 0).lower()}">{n + 1:02} {esc(f["title"])}</button>'
            )
            steps = []
            for k, step in enumerate(f["steps"]):
                stepid = ident + "-step-" + str(k + 1)
                steps.append(
                    f'<li id="{stepid}"><span class="step-number">{k + 1:02}</span><div><h4>{esc(step["title"])}</h4><p>{esc(step.get("detail", ""))}</p>{self.source_links(step.get("source", []))}</div></li>'
                )
                self.search.append(
                    {
                        "title": step["title"],
                        "chapter": f["title"],
                        "href": "#" + stepid,
                        "text": step.get("detail", ""),
                    }
                )
            diagram = f.get("diagram", {})
            diagram_html = ""
            if diagram.get("nodes"):
                flow_nodes[ident] = {
                    node["id"]: {
                        "title": node["title"],
                        "role": node.get("role", ""),
                        "sources": self.source_links(node.get("source", [])),
                    }
                    for node in diagram["nodes"]
                }
                diagram_html = (
                    f'<div class="trace-map" data-flow="{ident}">'
                    + self.flow_svg(diagram["nodes"], diagram.get("edges", []), ident,
                        "Select a node to inspect its behavior and source."
                        + (" Dashed arrows return to a later cycle." if any(edge.get("feedback") for edge in diagram.get("edges", [])) else ""))
                    + f'<div class="node-inspector" id="inspect-{ident}" aria-live="polite"></div></div>'
                )
            flows.append(
                f'<section class="trace-panel" id="{ident}" role="tabpanel" aria-labelledby="tab-{ident}"><h3>{esc(f["title"])}</h3><p class="trace-summary">{esc(f.get("summary", ""))}</p>'
                + diagram_html + '<ol class="trace-steps">'
                + "".join(steps)
                + "</ol></section>"
            )
        chapters = []
        nav = []
        for i, ch in enumerate(self.chapters):
            rendered = self.render_markdown(ch)
            words = len(ch["text"].split())
            nav.append(
                f'<a href="#{ch["id"]}" class="chapter-link"><span>{i + 1:02}</span>{esc(ch["label"])}</a>'
            )
            chapters.append(
                f'<article class="document" id="{ch["id"]}"><header class="document-header"><span class="eyebrow">FIELD GUIDE / {i + 1:02}</span><span class="reading-time">{max(1, round(words / 200))} MIN READ</span></header><div class="prose">{rendered}</div></article>'
            )
        source_sections = []
        for r in self.sources.values():
            location = "L" + str(r["line"]) if r["line"] else "empty"
            if r.get("endLine") is not None and r["endLine"] > r["line"]:
                location += "–" + str(r["endLine"])
            source_sections.append(
                f'<details class="source-record" id="{r["id"]}"><summary><span>{esc(r["path"])} <b>{location}</b></span><small>{esc(r["symbol"])}</small></summary><pre><code>{esc_code(r["excerpt"])}</code></pre></details>'
            )
            self.search.append(
                {
                    "title": r["symbol"] or r["path"],
                    "chapter": "Source map",
                    "href": "#" + r["id"],
                    "text": r["path"] + " " + r["symbol"],
                }
            )
        badge = '<svg viewBox="0 0 32 36" aria-hidden="true"><path d="M16 2 29 7v11c0 8-7 13-13 16C10 31 3 26 3 18V7Z" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="m9 12 7-3 7 3M9 18l7-3 7 3m-14 6 7-3 7 3" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>'
        content = f"""<a class="skip-link" href="#main">Skip to content</a>
<header class="topbar"><a class="brand" href="#overview">{badge}<span>GAINSEC <b>/</b> {esc(product)}</span></a><span class="topbar-label">SYSTEMS &amp; OPERATING CODEX</span><div class="top-actions"><button type="button" id="search-open" class="search-trigger">Search <kbd>⌘ K</kbd></button><button type="button" id="theme-toggle" class="icon-button" aria-label="Switch color theme">◐</button><button type="button" id="menu-toggle" class="icon-button mobile-only" aria-label="Open navigation" aria-expanded="false">☰</button></div></header>
<aside class="sidebar" id="navigation"><div class="sidebar-title">{esc(name)}</div><div class="eyebrow">TECHNICAL ATLAS</div><nav aria-label="Atlas navigation"><a href="#overview">Overview</a>{screenshot_nav}{control_nav}<a href="#capabilities">Capability atlas <small>{len(cards):02}</small></a><a href="#architecture">System architecture</a><a href="#walkthroughs">End-to-end traces</a><a href="#field-guides">Field guides <small>{len(self.chapters):02}</small></a><a href="#source-map">Source map</a></nav><div class="sidebar-divider"></div><div class="eyebrow">READ THE SYSTEM</div><nav class="chapter-navigation" aria-label="Documentation chapters">{"".join(nav)}</nav><div class="sidebar-footer">READY ARMOR<br><span>Architecture · Capability · Evidence</span></div></aside>
<main id="main"><section class="hero section" id="overview"><div class="hero-topline"><span class="eyebrow">READY ARMOR / {esc(product)}</span><span class="status-label"><i></i> CONTROL · CAPABILITY · EVIDENCE</span></div><h1>{esc(name)}</h1><p class="tagline">{esc(p.get("tagline", ""))}</p><p class="hero-summary">{esc(p.get("summary", ""))}</p><div class="hero-actions"><a class="primary-link" href="#architecture">Explore the architecture <span>↗</span></a><a class="secondary-link" href="#{self.chapters[0]["id"]}">Read the product guide →</a></div><div class="index-strip"><div><span>01</span><strong>Understand the approach</strong><small>Purpose, authority, and useful outcomes</small></div><div><span>02</span><strong>Trace the mechanisms</strong><small>Components, decisions, and durable state</small></div><div><span>03</span><strong>Operate the product</strong><small>Installation, workflows, and references</small></div></div></section>
{screenshots_html}<section class="section use-section" id="applications"><div class="section-heading"><span class="eyebrow">01 / IN PRACTICE</span><h2>Use cases and outcomes.</h2></div><div class="use-grid">{uses}</div></section>{control_html}
<section class="section" id="capabilities"><div class="section-heading"><span class="eyebrow">02 / CAPABILITY ATLAS</span><h2>What it does. How it works.</h2><p>Each capability connects an operating purpose to an implementation mechanism and its source entry points.</p></div><div class="feature-tools"><label for="feature-filter">Find a capability</label><input id="feature-filter" type="search" placeholder="Filter by feature or mechanism…" autocomplete="off"><span id="feature-count" aria-live="polite">{len(cards)} capabilities</span></div><div class="feature-grid">{"".join(cards)}</div><button type="button" id="feature-expand" class="expand-button" hidden>Show all capabilities</button></section>
<section class="section" id="architecture"><div class="section-heading"><span class="eyebrow">03 / SYSTEM ARCHITECTURE</span><h2>Follow the control and data.</h2><p>Read the layers, then select a component to inspect its responsibility and implementation.</p></div>{graph}<div class="node-inspector" id="node-inspector" aria-live="polite"></div></section>
<section class="section" id="walkthroughs"><div class="section-heading"><span class="eyebrow">04 / END-TO-END TRACES</span><h2>A complete path through the system.</h2><p>Follow each operation from its entry point through decisions, state changes, evidence, and review.</p></div><div class="trace-tabs" role="tablist" aria-label="Operating traces">{"".join(tabs)}</div>{"".join(flows)}</section>
<section class="section guide-intro" id="field-guides"><span class="eyebrow">05 / FIELD GUIDES</span><h2>The complete technical reading.</h2><p>Product concepts, architectural decisions, source-linked mechanisms, and operating instructions.</p><div class="chapter-directory">{"".join(nav)}</div></section>{"".join(chapters)}
<section class="section" id="source-map"><div class="section-heading"><span class="eyebrow">06 / SOURCE MAP</span><h2>Read the implementation.</h2><p>Source locations and excerpts connect the capability atlas and operating traces to the code.</p></div><div class="source-index">{"".join(source_sections)}</div></section><footer class="page-footer"><span>{esc(name)}</span><span>GAINSEC / READY ARMOR</span><a href="#overview">Back to the beginning ↑</a></footer></main>
<dialog id="search-dialog" aria-labelledby="search-title"><div class="dialog-top"><h2 id="search-title">Search the atlas</h2><button type="button" data-close-dialog aria-label="Close search">×</button></div><label class="sr-only" for="atlas-search">Search features, flows, documentation, and source</label><input id="atlas-search" type="search" autocomplete="off" placeholder="Find a feature, concept, procedure, or function…"><div id="search-summary" aria-live="polite"></div><div id="search-results"></div></dialog>
<dialog id="source-dialog" aria-labelledby="source-title"><div class="dialog-top"><h2 id="source-title">Source reference</h2><button type="button" data-close-dialog aria-label="Close source reference">×</button></div><p id="source-location"></p><pre><code id="source-code"></code></pre></dialog>"""
        if control_html:
            content = content.replace(
                '<a class="primary-link" href="#architecture">Explore the architecture',
                '<a class="primary-link" href="#control-in-depth">Explore Control in Depth',
            )
        arch_match = re.search(
            r'<section class="section" id="architecture">.*?</section>', content, re.S
        )
        if arch_match:
            arch = arch_match[0]
            content = content.replace(arch, "")
            content = content.replace(
                '<section class="section" id="capabilities">',
                arch + '<section class="section" id="capabilities">',
            )
            content = content.replace(
                "02 / CAPABILITY ATLAS", "03 / CAPABILITY ATLAS"
            ).replace("03 / SYSTEM ARCHITECTURE", "02 / SYSTEM ARCHITECTURE")
        content += """<dialog id="screenshot-dialog" aria-labelledby="screenshot-title"><div class="screenshot-toolbar"><div><span class="eyebrow">PRODUCT VIEW</span><h2 id="screenshot-title">Screenshot</h2></div><div class="screenshot-controls"><button type="button" id="screenshot-zoom" aria-pressed="false">Actual size</button><button type="button" data-close-dialog aria-label="Close screenshot">×</button></div></div><div class="screenshot-viewport" tabindex="0" aria-label="Full screenshot; scroll to inspect"><img id="screenshot-full" alt=""></div><div class="screenshot-footer"><p id="screenshot-caption"></p><div class="screenshot-controls"><button type="button" id="screenshot-prev" aria-label="Previous screenshot">←</button><span id="screenshot-position" aria-live="polite"></span><button type="button" id="screenshot-next" aria-label="Next screenshot">→</button></div></div></dialog>"""
        data = {"search": self.search, "sources": self.sources, "nodes": node_content, "screenshots": p.get("screenshots", []), "flowNodes": flow_nodes}
        accent = p.get("accent", "#c5a25c")
        palette = (
            "[data-theme=dark]{--accent:"
            + contrast_color(accent, "#16212e")
            + "}[data-theme=light]{--accent:"
            + contrast_color(accent, "#fffefa")
            + "}"
        )
        favicon = base64.b64encode(
            b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 36"><path d="M16 2 29 7v11c0 8-7 13-13 16C10 31 3 26 3 18V7Z" fill="#16212e" stroke="#d4b26c" stroke-width="2"/><path d="m9 12 7-3 7 3M9 18l7-3 7 3m-14 6 7-3 7 3" fill="none" stroke="#d4b26c" stroke-width="2"/></svg>'
        ).decode()
        output = (
            '<!doctype html>\n<html lang="en" data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="'
            + esc(p.get("summary", ""))
            + '"><meta name="color-scheme" content="dark light"><title>'
            + esc(name)
            + ' — Technical Atlas</title><link rel="icon" href="data:image/svg+xml;base64,'
            + favicon
            + '"><style>:root{--accent:'
            + esc(p.get("accent", "#c5a25c"))
            + "}\n"
            + CSS
            + palette
            + "</style></head><body>"
            + content
            + '<script type="application/json" id="atlas-data">'
            + json_text(data)
            + "</script><script>"
            + JS
            + "</script></body></html>\n"
        )
        publication = self.root / "docs"
        publication.mkdir(exist_ok=True)
        dest = publication / "index.html"
        dest.write_text(output)
        (publication / ".nojekyll").touch()
        return {
            "file": str(dest),
            "bytes": len(output.encode()),
            "chapters": len(self.chapters),
            "features": len(cards),
            "flows": len(flows),
            "sourceReferences": len(self.sources),
        }


CSS = r"""
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:100px}body{margin:0;font-family:Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;line-height:1.65;background:var(--bg);color:var(--ink);font-size:15px}:root{--bg:#0c1118;--surface:#111923;--raised:#16212e;--ink:#e6eaf0;--muted:#a4afbf;--dim:#8493a5;--rule:#293444;--code:#080d13;--accent-soft:color-mix(in srgb,var(--accent) 14%,transparent);--sidebar:246px;--topbar:70px}[data-theme=light]{--bg:#f7f6f2;--surface:#fffefa;--raised:#eceee9;--ink:#1b2934;--muted:#536273;--dim:#647386;--rule:#d9dedb;--code:#eef1ee;--accent-soft:color-mix(in srgb,var(--accent) 10%,transparent)}a{color:var(--accent);text-underline-offset:4px}button,input{font:inherit}button,a,input,summary{touch-action:manipulation}button{cursor:pointer}button:focus-visible,a:focus-visible,input:focus-visible,summary:focus-visible,.graph-node:focus-visible{outline:2px solid var(--accent);outline-offset:4px}::selection{background:var(--accent);color:var(--bg)}.skip-link{position:fixed;top:-90px;left:20px;z-index:200;padding:10px 18px;background:var(--ink);color:var(--bg)}.skip-link:focus{top:10px}.topbar{height:var(--topbar);position:fixed;inset:0 0 auto;z-index:30;display:flex;align-items:center;gap:32px;padding:0 30px;border-bottom:1px solid var(--rule);background:var(--bg)}.brand{display:flex;align-items:center;gap:12px;text-decoration:none;white-space:nowrap;color:var(--ink);letter-spacing:.14em;font-size:12px;font-weight:700}.brand svg{width:25px;height:30px;color:var(--accent)}.brand b{font-weight:400;color:var(--dim);padding:0 7px}.topbar-label{font:10px ui-monospace,SFMono-Regular,Consolas,monospace;letter-spacing:.16em;color:var(--dim)}.top-actions{display:flex;align-items:center;gap:12px;margin-left:auto}.search-trigger{color:var(--muted);background:var(--surface);border:1px solid var(--rule);border-radius:6px;padding:6px 12px;display:flex;align-items:center;gap:38px;font-size:12px}kbd{font:10px ui-monospace,monospace;color:var(--dim)}.icon-button{width:34px;height:34px;background:none;border:1px solid var(--rule);border-radius:6px;color:var(--muted);font-size:20px}.mobile-only{display:none}.sidebar{position:fixed;inset:var(--topbar) auto 0 0;width:var(--sidebar);padding:32px 23px 22px;border-right:1px solid var(--rule);overflow-y:auto;background:var(--bg);z-index:20;scrollbar-width:thin}.sidebar-title{font-size:16px;font-weight:650;line-height:1.4;margin-bottom:8px}.eyebrow{font:10px ui-monospace,SFMono-Regular,Consolas,monospace;letter-spacing:.13em;color:var(--accent);text-transform:uppercase}.sidebar>.eyebrow{color:var(--dim);font-size:9px;margin-bottom:22px}.sidebar nav{display:flex;flex-direction:column;gap:5px}.sidebar nav a{color:var(--muted);font-size:12px;text-decoration:none;padding:7px 8px;border-radius:5px;line-height:1.5}.sidebar nav a:hover,.sidebar nav a.active{background:var(--accent-soft);color:var(--ink)}.sidebar nav a.active{box-shadow:inset 2px 0 var(--accent)}.sidebar nav a small{float:right;font:10px ui-monospace,monospace;color:var(--dim);padding-top:3px}.sidebar-divider{height:1px;background:var(--rule);margin:22px 0}.sidebar .chapter-navigation{gap:1px}.chapter-link{display:flex;gap:10px}.chapter-link>span{font:10px ui-monospace,monospace;color:var(--dim);padding-top:3px;flex-shrink:0}.sidebar-footer{border-top:1px solid var(--rule);padding-top:24px;margin-top:30px;font:10px ui-monospace,monospace;letter-spacing:.08em;color:var(--accent)}.sidebar-footer span{font:10px ui-sans-serif,sans-serif;color:var(--dim);letter-spacing:0}main{margin-left:var(--sidebar);padding-top:var(--topbar);max-width:1820px}.section,.document{padding:62px clamp(24px,4.4vw,76px);border-bottom:1px solid var(--rule)}.hero{padding-top:44px;padding-bottom:0;position:relative;background:radial-gradient(ellipse at 100% 0,var(--accent-soft),transparent 57%)}.hero-topline{display:flex;align-items:center;justify-content:space-between;gap:15px}.status-label{font:8px ui-monospace,monospace;letter-spacing:.1em;color:var(--dim);display:flex;align-items:center;gap:7px}.status-label i{width:5px;height:5px;border-radius:50%;background:var(--accent)}h1,h2,h3,h4{line-height:1.25;letter-spacing:-.025em}h1{font-family:Georgia,"Times New Roman",serif;font-size:clamp(40px,5.5vw,86px);font-weight:400;max-width:1050px;margin:30px 0 14px;line-height:1.05}.tagline{font-size:clamp(18px,2.1vw,28px);font-weight:450;color:var(--ink);letter-spacing:-.025em;max-width:900px;margin:0 0 17px}.hero-summary{font-size:15px;max-width:790px;color:var(--muted);line-height:1.8}.hero-actions{display:flex;align-items:center;gap:25px;margin:26px 0 37px}.primary-link{display:inline-flex;align-items:center;justify-content:space-between;gap:28px;text-decoration:none;background:var(--accent);color:#081016;border:1px solid var(--accent);padding:10px 15px;border-radius:4px;font-size:12px;font-weight:650}.secondary-link{font-size:12px;color:var(--muted);text-decoration:none}.index-strip{display:grid;grid-template-columns:repeat(3,1fr);border-top:1px solid var(--rule)}.index-strip>div{padding:21px 16px 22px 0;display:grid;grid-template-columns:28px 1fr;column-gap:9px}.index-strip>div+div{border-left:1px solid var(--rule);padding-left:20px}.index-strip span{grid-row:span 2;font:10px ui-monospace,monospace;color:var(--accent);padding-top:3px}.index-strip strong{font-size:11px;font-weight:550}.index-strip small{font-size:10px;color:var(--dim);margin-top:4px}.section-heading{margin-bottom:26px}.section-heading h2,.guide-intro h2{font-family:Georgia,"Times New Roman",serif;font-size:clamp(27px,3.2vw,43px);font-weight:400;margin:15px 0 14px;line-height:1.16}.section-heading>p,.guide-intro>p{color:var(--muted);max-width:800px;font-size:13px}.use-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;border:1px solid var(--rule);background:var(--rule);border-radius:6px;overflow:hidden}.use-card{background:var(--surface);padding:25px}.use-card h3{font-size:16px;margin:0 0 12px}.use-card p{font-size:12px;color:var(--muted);line-height:1.8;margin-bottom:21px}.outcome{border-top:1px solid var(--rule);padding-top:14px;font-size:11px;color:var(--accent)}.feature-tools{display:flex;align-items:center;gap:18px;border-top:1px solid var(--rule);border-bottom:1px solid var(--rule);padding:15px 0;margin-bottom:24px}.feature-tools label{font-size:11px;color:var(--muted)}.feature-tools input{background:var(--surface);border:1px solid var(--rule);border-radius:4px;padding:8px 11px;color:var(--ink);font-size:12px;flex:1;max-width:400px;min-width:0}.feature-tools>span{font:10px ui-monospace,monospace;color:var(--dim);margin-left:auto;white-space:nowrap}.feature-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:15px}.feature-card{border:1px solid var(--rule);border-radius:6px;padding:24px;background:var(--surface);min-width:0;scroll-margin-top:90px}.feature-card>.eyebrow{font-size:8px;color:var(--dim)}.feature-card h3{font-size:19px;margin:13px 0 12px}.feature-card p{font-size:13px;line-height:1.8;color:var(--muted);margin:0 0 16px}.mechanism{font-size:11px;line-height:1.85;border-top:1px solid var(--rule);padding-top:14px;color:var(--muted)}.expand-button{display:block;margin:25px auto 0;padding:10px 24px;border:1px solid var(--rule);background:var(--surface);color:var(--accent);border-radius:4px;font-size:12px}.source-links{display:flex;flex-wrap:wrap;gap:6px;margin-top:14px}.source-link{display:inline-flex;align-items:center;gap:5px;max-width:100%;overflow-wrap:anywhere;border:1px solid var(--rule);border-radius:3px;padding:3px 6px;font:9px ui-monospace,SFMono-Regular,Consolas,monospace;text-decoration:none;color:var(--muted);background:var(--bg)}.source-link:hover{border-color:var(--accent);color:var(--accent)}.source-link>span{color:var(--accent)}.source-link small{font:8px ui-monospace,monospace;color:var(--dim);white-space:nowrap}.diagram{margin:25px 0 0;border:1px solid var(--rule);border-radius:6px;overflow:hidden;background:var(--surface)}.diagram-scroll{overflow:auto;padding:8px;scrollbar-width:thin}.system-svg{display:block;width:100%;min-width:660px;color:var(--accent);font-family:ui-sans-serif,sans-serif}.diagram figcaption{font-size:10px;color:var(--dim);padding:12px 16px;border-top:1px solid var(--rule)}.layer-label{fill:var(--dim);font:9px ui-monospace,monospace;letter-spacing:2px}.graph-edge{opacity:.4}.graph-edge path{stroke:var(--dim);stroke-width:1.1;fill:none}.graph-edge.is-related{opacity:1}.graph-edge.is-related path{stroke:var(--accent);stroke-width:1.8}.graph-node{cursor:pointer;outline:none}.graph-node rect{fill:var(--raised);stroke:var(--rule);stroke-width:1.2}.graph-node:hover rect,.graph-node:focus rect,.graph-node.is-selected rect{stroke:var(--accent);fill:var(--accent-soft)}.node-title{fill:var(--ink);font-size:13px;font-weight:600}.node-role{fill:var(--muted);font-size:10px}.node-index{fill:var(--dim);font:8px ui-monospace,monospace}.node-inspector{border:1px solid var(--rule);border-top:0;border-radius:0 0 6px 6px;background:var(--surface);padding:20px 24px;min-height:130px}.node-inspector h3{font-size:16px;margin:0 0 7px}.node-inspector p{font-size:12px;color:var(--muted);margin:0}.trace-tabs{display:flex;gap:0;overflow:auto;border-bottom:1px solid var(--rule);margin-bottom:28px}.trace-tab{padding:12px 17px;white-space:nowrap;background:none;border:0;border-bottom:2px solid transparent;color:var(--muted);font-size:11px}.trace-tab[aria-selected=true]{color:var(--accent);border-color:var(--accent);background:var(--accent-soft)}.trace-panel>h3{font-size:24px;margin:0 0 10px}.trace-summary{color:var(--muted);font-size:13px;max-width:800px}.trace-steps{list-style:none;padding:0;margin:30px 0 0}.trace-steps>li{display:grid;grid-template-columns:48px minmax(0,1fr);gap:23px;position:relative;padding:0 0 29px}.trace-steps>li:not(:last-child):before{content:"";position:absolute;left:20px;top:40px;width:1px;height:calc(100% - 40px);background:var(--rule)}.step-number{width:41px;height:41px;border:1px solid var(--rule);background:var(--surface);border-radius:50%;display:grid;place-items:center;color:var(--accent);font:11px ui-monospace,monospace}.trace-steps h4{margin:7px 0 8px;font-size:16px}.trace-steps p{font-size:13px;color:var(--muted);line-height:1.8;margin:0;max-width:850px}.trace-steps .source-links{margin-top:10px}.chapter-directory{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;background:var(--rule);border:1px solid var(--rule);border-radius:5px;overflow:hidden;margin-top:25px}.chapter-directory a{background:var(--surface);padding:14px 16px;color:var(--muted);text-decoration:none;font-size:12px}.chapter-directory a:hover{color:var(--accent);background:var(--raised)}.document{background:var(--surface);scroll-margin-top:70px}.document:nth-of-type(even){background:var(--bg)}.document-header{display:flex;justify-content:space-between;border-bottom:1px solid var(--rule);padding-bottom:16px;margin-bottom:33px}.reading-time{font:9px ui-monospace,monospace;color:var(--dim);letter-spacing:.06em}.prose{max-width:1050px}.prose>h2:first-child{font-family:Georgia,"Times New Roman",serif;font-size:42px;font-weight:400;margin-top:0}.prose h2{font-size:30px;margin:40px 0 20px}.prose h3{font-size:23px;margin:35px 0 16px;border-top:1px solid var(--rule);padding-top:25px}.prose h4{font-size:17px;margin:29px 0 12px}.prose h5,.prose h6{font-size:15px;margin:22px 0 10px}.prose p{font-size:14px;line-height:1.9;color:var(--muted);margin:14px 0;max-width:94ch}.prose li{font-size:13px;line-height:1.9;color:var(--muted);margin:7px 0;max-width:94ch}.prose ul,.prose ol{padding-left:24px}.prose strong{color:var(--ink);font-weight:600}.prose blockquote{margin:22px 0;padding:8px 22px;border-left:2px solid var(--accent);color:var(--muted);font-size:13px;background:var(--accent-soft)}code{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:.88em;overflow-wrap:anywhere}.prose :not(pre)>code{background:var(--raised);padding:2px 5px;border-radius:3px;color:var(--ink)}pre{font:11px/1.9 ui-monospace,SFMono-Regular,Consolas,monospace;overflow:auto;tab-size:4;white-space:pre;margin:0;padding:20px 22px;background:var(--code);color:var(--ink)}pre code{font:inherit;overflow-wrap:normal}.code-block{border:1px solid var(--rule);border-radius:5px;overflow:hidden;margin:22px 0}.code-bar{display:flex;justify-content:space-between;align-items:center;padding:8px 13px;background:var(--raised);font:9px ui-monospace,monospace;color:var(--dim);text-transform:uppercase;letter-spacing:.08em}.copy-button{font:10px ui-monospace,monospace;color:var(--muted);border:0;background:none;padding:1px 5px;text-transform:none}.table-scroll{width:100%;overflow:auto;border:1px solid var(--rule);border-radius:4px;margin:22px 0}table{border-collapse:collapse;width:100%;font-size:12px;min-width:420px}th{text-align:left;padding:12px 15px;background:var(--raised);font-weight:600;white-space:nowrap}td{padding:12px 15px;border-top:1px solid var(--rule);color:var(--muted);vertical-align:top;line-height:1.8;min-width:110px}td a{overflow-wrap:anywhere}hr{border:0;border-top:1px solid var(--rule);margin:30px 0}.permalink{font-size:12px;text-decoration:none;opacity:0;margin-left:9px;color:var(--dim)}h2:hover>.permalink,h3:hover>.permalink,h4:hover>.permalink,.permalink:focus{opacity:1}.source-index{display:flex;flex-direction:column;gap:9px}.source-record{border:1px solid var(--rule);border-radius:4px;overflow:hidden;scroll-margin-top:100px}.source-record summary{padding:13px 16px;cursor:pointer;background:var(--surface);font:11px/1.7 ui-monospace,monospace;overflow-wrap:anywhere}.source-record summary b{font-weight:400;color:var(--accent)}.source-record summary small{display:block;color:var(--dim);padding-left:15px}.source-record pre{border-top:1px solid var(--rule)}.page-footer{padding:35px clamp(24px,4.4vw,76px);display:flex;flex-wrap:wrap;justify-content:space-between;gap:14px;font:9px ui-monospace,monospace;color:var(--dim);letter-spacing:.04em}.page-footer a{color:var(--muted);text-decoration:none}dialog{background:var(--surface);color:var(--ink);border:1px solid var(--rule);border-radius:10px;padding:22px;width:min(760px,calc(100% - 32px));max-height:80vh;box-shadow:0 30px 100px #0008}dialog::backdrop{background:#02060bd9;backdrop-filter:blur(5px)}.dialog-top{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:20px}.dialog-top h2{font-size:19px;margin:0}.dialog-top button{border:0;background:none;color:var(--muted);font-size:27px;line-height:1}.dialog-top+input{width:100%;padding:13px;border:1px solid var(--rule);border-radius:5px;background:var(--bg);color:var(--ink);font-size:14px}#search-summary{font:10px ui-monospace,monospace;color:var(--dim);margin:13px 0}#search-results{display:flex;flex-direction:column;gap:7px}#search-results a{display:block;padding:13px 15px;background:var(--bg);border:1px solid var(--rule);border-radius:4px;text-decoration:none}#search-results a:hover{border-color:var(--accent)}#search-results strong{font-size:13px;color:var(--ink)}#search-results small{display:block;font:9px ui-monospace,monospace;color:var(--accent);margin-bottom:5px}#search-results p{font-size:11px;color:var(--muted);margin:6px 0 0}#source-dialog{width:min(1040px,calc(100% - 32px))}#source-location{font:11px ui-monospace,monospace;color:var(--accent);overflow-wrap:anywhere}#source-dialog pre{max-height:55vh;border:1px solid var(--rule);border-radius:5px}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}[hidden]{display:none!important}
@media(min-width:1600px){.feature-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:1150px){:root{--sidebar:218px}.topbar-label{display:none}.section,.document{padding-left:32px;padding-right:32px}.use-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.index-strip small{display:none}.chapter-directory{grid-template-columns:repeat(2,minmax(0,1fr))}.hero-topline .status-label{font-size:7px}.index-strip strong{font-size:10px}.use-card{padding:20px}}@media(max-width:850px){:root{--sidebar:0px;--topbar:60px}.topbar{padding:0 18px;gap:10px}.brand{font-size:10px;gap:9px}.brand svg{width:21px}.search-trigger{gap:15px}.mobile-only{display:block}.sidebar{width:275px;transform:translateX(-100%);transition:transform .2s ease;box-shadow:24px 0 55px #0005}.sidebar.is-open{transform:translateX(0)}.section,.document{padding:39px 24px}.hero{padding-top:31px;padding-bottom:0}h1{font-size:54px;margin-top:27px}.hero-topline .status-label{display:none}.hero-summary{font-size:14px}.hero-actions{gap:18px;flex-wrap:wrap}.index-strip>div{padding:18px 10px 18px 0;grid-template-columns:19px 1fr;column-gap:5px}.index-strip>div+div{padding-left:12px}.index-strip strong{font-size:10px}.index-strip span{font-size:8px}.feature-card{padding:19px}.section-heading h2,.guide-intro h2{font-size:34px}.feature-tools{gap:12px}.feature-tools label{display:none}.feature-tools input{max-width:none}.document>.prose>h2:first-child{font-size:34px}.use-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.source-link{font-size:9px}.top-actions{gap:7px}.system-svg{min-width:660px}.prose p{font-size:13px}.prose h3{font-size:21px}}@media(max-width:520px){h1{font-size:45px}.tagline{font-size:21px}.section,.document{padding-left:19px;padding-right:19px}.feature-grid,.use-grid{grid-template-columns:minmax(0,1fr)}.feature-card h3{font-size:19px}.chapter-directory{grid-template-columns:minmax(0,1fr)}.index-strip strong{font-size:9px}.index-strip span{display:none}.index-strip>div{display:block}.hero-actions .primary-link{padding:9px 12px;gap:17px}.secondary-link{font-size:11px}.hero-summary{font-size:13px}.search-trigger{padding:5px 9px;font-size:11px}.search-trigger kbd{display:none}.trace-steps>li{grid-template-columns:36px minmax(0,1fr);gap:13px}.step-number{width:33px;height:33px;font-size:10px}.trace-steps>li:not(:last-child):before{left:16px;top:33px;height:calc(100% - 33px)}.trace-steps h4{font-size:15px;margin-top:4px}.prose>h2:first-child{font-size:30px!important}.prose h3{font-size:20px}.prose h4{font-size:16px}.prose li{font-size:12px}.code-block pre{padding:15px}dialog{padding:17px}.page-footer{padding:25px 19px}.feature-tools>span{font-size:8px}.node-inspector{padding:17px}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}*{transition:none!important}}@media print{:root{--bg:#fff;--surface:#fff;--raised:#f1f3f4;--ink:#111;--muted:#333;--dim:#555;--rule:#ccc;--code:#f5f5f5;--accent:#2d5160}.topbar,.sidebar,.hero-actions,.feature-tools,.copy-button,dialog,.permalink,.node-inspector,.trace-tabs,.skip-link{display:none!important}main{margin:0;padding:0;max-width:none}.section,.document{padding:22px 0;break-inside:auto}.hero{background:none}.system-svg{min-width:0}.diagram-scroll{overflow:visible}.feature-card,.use-card,.source-record,.trace-steps>li{break-inside:avoid}.feature-grid{grid-template-columns:repeat(2,1fr)}.trace-panel[hidden],.feature-card[hidden]{display:block!important}.source-record:not([open]) pre{display:none}h1{font-size:42px}.section-heading h2,.guide-intro h2{font-size:30px}.prose h3{break-after:avoid}.table-scroll{overflow:visible}pre{white-space:pre-wrap;font-size:9px}.document-header{margin-bottom:20px}a{text-decoration:none;color:#193f52}.page-footer{padding:20px 0}}
"""

CSS += ".control-order{font:11px/1.8 ui-monospace,SFMono-Regular,Consolas,monospace;color:var(--dim);border-top:1px solid var(--rule);padding-top:17px;margin:0 0 24px}.control-layout{display:grid;grid-template-columns:minmax(210px,.7fr) minmax(0,1.3fr);gap:24px;align-items:start}.control-rail{display:flex;flex-direction:column;gap:0;border:1px solid var(--rule);border-radius:6px;overflow:hidden}.control-tab{display:grid;grid-template-columns:28px minmax(0,1fr);align-items:start;gap:12px;text-align:left;background:var(--surface);color:var(--muted);border:0;padding:17px 15px;border-bottom:1px solid var(--rule);min-height:78px}.control-tab:last-child{border-bottom:0}.control-tab[aria-selected=true]{background:var(--accent-soft);box-shadow:inset 3px 0 var(--accent);color:var(--ink)}.control-number{font:10px ui-monospace,monospace;color:var(--accent);padding-top:3px}.control-tab strong{display:block;font-size:12px;font-weight:600;line-height:1.55}.control-tab small{display:block;font:9px/1.5 ui-monospace,monospace;color:var(--dim);margin-top:6px;text-transform:uppercase;letter-spacing:.04em}.control-panels{min-width:0;position:sticky;top:94px;max-height:calc(100vh - 114px);overflow-y:auto;scrollbar-width:thin}.control-panel{background:var(--surface);border:1px solid var(--rule);border-radius:6px;padding:25px;scroll-margin-top:100px}.control-panel+.control-panel{margin-top:16px}.js .control-panel+.control-panel{margin-top:0}.control-panel-heading{display:flex;justify-content:space-between;gap:15px;align-items:center}.control-kind{font:9px ui-monospace,monospace;color:var(--muted);border:1px solid var(--rule);border-radius:3px;padding:5px 7px;text-transform:uppercase;letter-spacing:.04em}.control-panel h3{font-size:24px;margin:20px 0 23px}.control-fields{margin:0}.control-field{border-top:1px solid var(--rule);padding:15px 0}.control-field dt{font:9px ui-monospace,monospace;text-transform:uppercase;letter-spacing:.07em;color:var(--accent);margin-bottom:8px}.control-field dd{overflow-wrap:anywhere;font-size:12px;line-height:1.85;color:var(--muted);margin:0}.control-example{background:var(--bg);border:1px solid var(--rule);border-radius:4px;padding:16px;margin-top:8px}.control-example h4{font-size:12px;letter-spacing:0;margin:0 0 16px}.control-example>div{display:grid;grid-template-columns:48px minmax(0,1fr);gap:12px}.control-example>div+div{margin-top:13px;padding-top:13px;border-top:1px solid var(--rule)}.control-example span{font:8px/1.8 ui-monospace,monospace;color:var(--dim);padding-top:2px;letter-spacing:.08em}.control-example p{overflow-wrap:anywhere;font-size:11px;line-height:1.85;margin:0;color:var(--muted)}\n@media(max-width:1050px){.control-layout{grid-template-columns:minmax(190px,.7fr) minmax(0,1.3fr);gap:16px}.control-panel{padding:19px}.control-panel h3{font-size:21px}.control-tab{padding:15px 12px;gap:7px;grid-template-columns:23px minmax(0,1fr)}}\n@media(max-width:700px){.control-layout{display:block}.control-rail{flex-direction:row;overflow-x:auto;border-radius:5px;margin-bottom:18px;scrollbar-width:thin}.control-tab{flex:0 0 220px;border-right:1px solid var(--rule);border-bottom:0;min-height:90px}.control-tab[aria-selected=true]{box-shadow:inset 0 -3px var(--accent)}.control-panels{position:static;max-height:none;overflow:visible}.control-panel-heading{flex-wrap:wrap}.control-panel{padding:20px}.control-order{font-size:10px}.control-example>div{grid-template-columns:40px minmax(0,1fr);gap:9px}}\n@media print{.control-rail{display:none}.control-layout{display:block}.control-panels{position:static;max-height:none;overflow:visible}.control-panel[hidden]{display:block!important}.control-panel{break-inside:avoid;margin-top:16px!important}.control-example,.control-panel{background:white}.control-panel h3{font-size:19px}.control-field{padding:9px 0}.control-field dd{font-size:10px}.control-example p{font-size:10px}}\n"

CSS += '\n.screenshot-directory{display:flex;flex-wrap:wrap;gap:9px;margin:0 0 24px}.screenshot-directory a{display:inline-flex;gap:11px;align-items:center;padding:8px 12px;border:1px solid var(--rule);border-radius:4px;text-decoration:none;color:var(--muted);font-size:11px;background:var(--surface)}.screenshot-directory a:hover{border-color:var(--accent);color:var(--ink)}.screenshot-directory small{font:9px ui-monospace,monospace;color:var(--accent)}\n.screenshot-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:22px}.screenshot-card{margin:0;min-width:0;border:1px solid var(--rule);background:var(--surface);border-radius:6px;overflow:hidden;scroll-margin-top:100px}.screenshot-card:first-child{grid-column:1/-1}.screenshot-open{position:relative;display:block;padding:0;width:100%;border:0;color:#edf1f8;background:#080e17;cursor:zoom-in;overflow:hidden;text-align:left}.screenshot-preview{display:block;width:100%;height:270px;object-fit:cover;object-position:top;transition:opacity .18s ease}.screenshot-card:first-child .screenshot-preview{height:450px}.screenshot-open:hover .screenshot-preview{opacity:.85}.screenshot-open:focus-visible{outline:3px solid var(--accent);outline-offset:-3px}.screenshot-action{position:absolute;bottom:14px;right:14px;border:1px solid #536279;background:#101a28ed;border-radius:4px;padding:7px 11px;font:10px/1.5 ui-monospace,monospace;color:#eef3fa}.screenshot-card figcaption{padding:21px 23px}.screenshot-card[data-image-kind=architecture] .screenshot-preview{object-fit:contain}.screenshot-card h3{margin:9px 0;font-size:19px}.screenshot-card figcaption p{margin:0;color:var(--muted);font-size:12px;line-height:1.9}.screenshot-inline{display:block;margin:22px 0;border:1px solid var(--rule);border-radius:5px;overflow:hidden}.screenshot-inline .screenshot-preview{height:auto;max-height:420px;object-fit:cover;object-position:top}#screenshot-dialog{width:min(1280px,96vw);max-width:96vw;padding:0;max-height:94dvh;overflow:hidden}#screenshot-dialog[open]{display:flex;flex-direction:column}.screenshot-toolbar{display:flex;justify-content:space-between;align-items:center;gap:16px;padding:17px 22px;border-bottom:1px solid var(--rule);flex-shrink:0}.screenshot-toolbar h2{font-size:18px;margin:4px 0 0}.screenshot-controls{display:flex;align-items:center;gap:10px;flex-shrink:0}.screenshot-controls button{padding:8px 12px;border:1px solid var(--rule);border-radius:4px;background:var(--raised);color:var(--ink);font:11px/1.5 ui-monospace,monospace;min-width:36px;min-height:36px}.screenshot-controls button[aria-pressed=true]{border-color:var(--accent);color:var(--accent)}.screenshot-viewport{overflow:auto;min-height:0;background:#080e17;overscroll-behavior:contain;scrollbar-width:thin}.screenshot-viewport img{display:block;width:auto;max-width:100%;height:auto;margin:0 auto}.screenshot-viewport.actual-size img{max-width:none;margin:0}.screenshot-footer{display:flex;align-items:center;justify-content:space-between;gap:22px;padding:15px 22px;border-top:1px solid var(--rule);flex-shrink:0}.screenshot-footer p{margin:0;color:var(--muted);font-size:11px;line-height:1.8}.screenshot-footer span{font:10px ui-monospace,monospace;color:var(--muted);white-space:nowrap}\n@media(max-width:700px){.screenshot-grid{grid-template-columns:minmax(0,1fr);gap:18px}.screenshot-card:first-child{grid-column:auto}.screenshot-card:first-child .screenshot-preview,.screenshot-preview{height:230px}.screenshot-card figcaption{padding:18px}.screenshot-inline .screenshot-preview{max-height:300px}.screenshot-toolbar{padding:14px;gap:10px}.screenshot-toolbar h2{font-size:14px}.screenshot-controls{gap:6px}.screenshot-controls button{padding:7px 9px;font-size:10px}.screenshot-footer{padding:14px;align-items:flex-start;gap:12px;flex-direction:column}.screenshot-footer .screenshot-controls{align-self:flex-end}}\n@media(prefers-reduced-motion:reduce){.screenshot-preview{transition:none}}\n@media print{.screenshot-grid{grid-template-columns:1fr}.screenshot-card,.screenshot-inline{break-inside:avoid;border-color:#bbb}.screenshot-preview,.screenshot-card:first-child .screenshot-preview,.screenshot-inline .screenshot-preview{height:auto;max-height:650px;object-fit:contain}.screenshot-action{display:none}.screenshot-open{background:white}#screenshot-dialog[open]{display:none!important}}\n'

CSS += ".trace-map{margin:25px 0 32px}.trace-map .diagram{margin:0}.trace-map .node-inspector{margin-top:14px}.feedback-edge path{stroke-dasharray:7 5;stroke-linejoin:round}.trace-map .graph-node.is-selected rect{stroke:var(--accent);stroke-width:2}.trace-map .graph-edge.is-related path{stroke:var(--accent);opacity:1}"

JS = r"""
(()=>{'use strict';const data=JSON.parse(document.getElementById('atlas-data').textContent),$=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];document.documentElement.classList.add('js');
try{const theme=localStorage.getItem('ready-armor-theme');if(theme==='light'||theme==='dark')document.documentElement.dataset.theme=theme}catch(e){}
$('#theme-toggle').addEventListener('click',()=>{const theme=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=theme;try{localStorage.setItem('ready-armor-theme',theme)}catch(e){}});
const mobile=matchMedia('(max-width:850px)');function navState(){const open=$('#navigation').classList.contains('is-open');$('#navigation').inert=mobile.matches&&!open;$('#menu-toggle').setAttribute('aria-expanded',String(open))}mobile.addEventListener('change',navState);navState();$('#menu-toggle').addEventListener('click',()=>{$('#navigation').classList.toggle('is-open');navState()});
function reveal(href){const id=decodeURIComponent(href.slice(1)),target=document.getElementById(id);if(!target)return;const section=target.closest('main>.section,main>.document');$$('.sidebar a').forEach(a=>a.classList.toggle('active',a.hash===href||a.hash==='#'+section?.id));const control=target.closest('.control-panel');if(control)selectControl(control.id);const panel=target.closest('.trace-panel');if(panel)selectTrace(panel.id);if(target.tagName==='DETAILS')target.open=true;if(target.classList.contains('feature-card')){$('#feature-filter').value='';expandFeatures=true;filterFeatures()}target.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});$('#navigation').classList.remove('is-open');$('#menu-toggle').setAttribute('aria-expanded','false');navState()}
function selectTrace(id){$$('.trace-panel').forEach(p=>p.hidden=p.id!==id);$$('.trace-tab').forEach(b=>b.setAttribute('aria-selected',String(b.getAttribute('aria-controls')===id)))}
function selectControl(id){const viewport=$('.control-panels');if(viewport)viewport.scrollTop=0;$$('.control-panel').forEach(p=>p.hidden=p.id!==id);$$('.control-tab').forEach(b=>{const selected=b.dataset.control===id;b.setAttribute('aria-selected',String(selected));b.tabIndex=selected?0:-1})}
const firstControl=$('.control-panel');if(firstControl)selectControl(firstControl.id);
const controlLayout=matchMedia('(max-width:700px)');function syncControlLayout(){$$('.control-rail').forEach(rail=>rail.setAttribute('aria-orientation',controlLayout.matches?'horizontal':'vertical'))}controlLayout.addEventListener('change',syncControlLayout);syncControlLayout();
$$('.control-tab').forEach(b=>b.addEventListener('click',()=>selectControl(b.dataset.control)));
$$('.control-rail').forEach(rail=>rail.addEventListener('keydown',e=>{const keys=['ArrowDown','ArrowUp','ArrowRight','ArrowLeft','Home','End'];if(!keys.includes(e.key))return;const tabs=[...rail.querySelectorAll('button')],current=tabs.indexOf(document.activeElement);if(current<0)return;e.preventDefault();let index;if(e.key==='Home')index=0;else if(e.key==='End')index=tabs.length-1;else index=(current+(['ArrowDown','ArrowRight'].includes(e.key)?1:tabs.length-1))%tabs.length;tabs[index].focus();selectControl(tabs[index].dataset.control)}));

const firstTrace=$('.trace-panel');if(firstTrace)selectTrace(firstTrace.id);$$('.trace-tab').forEach(b=>b.addEventListener('click',()=>selectTrace(b.getAttribute('aria-controls'))));
$$('.trace-tabs').forEach(list=>list.addEventListener('keydown',e=>{if(e.key!=='ArrowRight'&&e.key!=='ArrowLeft')return;const tabs=[...list.querySelectorAll('button')],n=tabs.indexOf(document.activeElement);if(n<0)return;e.preventDefault();const next=tabs[(n+(e.key==='ArrowRight'?1:tabs.length-1))%tabs.length];next.focus();next.click()}));
function inspectNode(id){const n=data.nodes[id];if(!n)return;const box=$('#node-inspector');box.replaceChildren();const h=document.createElement('h3');h.textContent=n.title;const p=document.createElement('p');p.textContent=n.role;box.append(h,p);const sources=document.createElement('div');sources.innerHTML=n.sources;box.append(sources);$$('#architecture .graph-node').forEach(g=>g.classList.toggle('is-selected',g.dataset.node===id));$$('#architecture .graph-edge').forEach(g=>g.classList.toggle('is-related',g.dataset.from===id||g.dataset.to===id))}
$$('#architecture .graph-node').forEach(n=>{n.addEventListener('click',()=>inspectNode(n.dataset.node));n.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();inspectNode(n.dataset.node)}})});if(Object.keys(data.nodes).length)inspectNode(Object.keys(data.nodes)[0]);


$$('.trace-map').forEach(map=>{const nodes=data.flowNodes?.[map.dataset.flow]||{};function select(id){const n=nodes[id];if(!n)return;const box=map.querySelector('.node-inspector');box.replaceChildren();const title=document.createElement('h3');title.textContent=n.title;const body=document.createElement('p');body.textContent=n.role;const links=document.createElement('div');links.innerHTML=n.sources;box.append(title,body,links);map.querySelectorAll('.graph-node').forEach(g=>g.classList.toggle('is-selected',g.dataset.node===id));map.querySelectorAll('.graph-edge').forEach(g=>g.classList.toggle('is-related',g.dataset.from===id||g.dataset.to===id))}map.querySelectorAll('.graph-node').forEach(node=>{node.addEventListener('click',()=>select(node.dataset.node));node.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();select(node.dataset.node)}})});if(Object.keys(nodes).length)select(Object.keys(nodes)[0])});

const embeddedImages=new Map($$('.screenshot-card [data-screenshot]').map(b=>[b.dataset.screenshot,b.querySelector('img').getAttribute('src')]));$$('img[data-image-ref]').forEach(img=>{const src=embeddedImages.get(img.dataset.imageRef);if(src)img.src=src});
const screenshotDialog=$('#screenshot-dialog'),screenshotFull=$('#screenshot-full'),screenshotViewport=$('.screenshot-viewport');
const screenshots=new Map((data.screenshots||[]).map(s=>[s.path,s]));$$('[data-screenshot]').forEach(b=>{if(!screenshots.has(b.dataset.screenshot))screenshots.set(b.dataset.screenshot,{path:b.dataset.screenshot,title:b.querySelector('img').alt,alt:b.querySelector('img').alt,caption:''})});const screenshotList=[...screenshots.values()];let screenshotIndex=0;
function setScreenshot(index){if(!screenshotList.length)return;screenshotIndex=(index+screenshotList.length)%screenshotList.length;const s=screenshotList[screenshotIndex],original=$$('[data-screenshot]').find(b=>b.dataset.screenshot===s.path)?.querySelector('img');if(!original)return;$('#screenshot-title').textContent=s.title;screenshotFull.src=original.src;screenshotFull.alt=s.alt;$('#screenshot-caption').textContent=s.caption;$('#screenshot-position').textContent=(screenshotIndex+1)+' / '+screenshotList.length;screenshotViewport.classList.remove('actual-size');$('#screenshot-zoom').setAttribute('aria-pressed','false');$('#screenshot-zoom').textContent='Actual size';screenshotViewport.scrollTop=0;screenshotViewport.scrollLeft=0;$('#screenshot-prev').disabled=$('#screenshot-next').disabled=screenshotList.length<2}
$$('[data-screenshot]').forEach(b=>b.addEventListener('click',()=>{setScreenshot(screenshotList.findIndex(s=>s.path===b.dataset.screenshot));if(!screenshotDialog.open)screenshotDialog.showModal()}));$('#screenshot-prev').addEventListener('click',()=>setScreenshot(screenshotIndex-1));$('#screenshot-next').addEventListener('click',()=>setScreenshot(screenshotIndex+1));$('#screenshot-zoom').addEventListener('click',()=>{const full=screenshotViewport.classList.toggle('actual-size');$('#screenshot-zoom').setAttribute('aria-pressed',String(full));$('#screenshot-zoom').textContent=full?'Fit width':'Actual size'});screenshotDialog.addEventListener('keydown',e=>{if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();setScreenshot(screenshotIndex+(e.key==='ArrowRight'?1:-1))}});

const searchDialog=$('#search-dialog'),sourceDialog=$('#source-dialog');function openSearch(){if(!searchDialog.open)searchDialog.showModal();$('#atlas-search').focus();renderSearch()}
$('#search-open').addEventListener('click',openSearch);document.addEventListener('keydown',e=>{if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();openSearch()}});$$('[data-close-dialog]').forEach(b=>b.addEventListener('click',()=>b.closest('dialog').close()));$$('dialog').forEach(d=>d.addEventListener('click',e=>{if(e.target===d){const r=d.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)d.close()}}));
function renderSearch(){const q=$('#atlas-search').value.trim().toLowerCase(),terms=q.split(/\s+/).filter(Boolean),container=$('#search-results');container.replaceChildren();if(!terms.length){$('#search-summary').textContent='Search capabilities, operating traces, field guides, and implementation symbols.';return}const results=data.search.map(x=>({x,score:terms.reduce((s,t)=>s+(x.title.toLowerCase().includes(t)?8:0)+(x.chapter.toLowerCase().includes(t)?3:0)+(x.text.toLowerCase().includes(t)?1:0),0)})).filter(r=>terms.every(t=>(r.x.title+' '+r.x.chapter+' '+r.x.text).toLowerCase().includes(t))).sort((a,b)=>b.score-a.score);$('#search-summary').textContent=results.length+' results';for(const {x} of results.slice(0,60)){const a=document.createElement('a');a.href=x.href;const k=document.createElement('small');k.textContent=x.chapter;const h=document.createElement('strong');h.textContent=x.title;const p=document.createElement('p');const clean=x.text.replace(/[`#*_]/g,''),at=clean.toLowerCase().indexOf(terms[0]),start=Math.max(0,at-60);p.textContent=(start?'…':'')+clean.slice(start,start+190);a.append(k,h,p);a.addEventListener('click',()=>searchDialog.close());container.append(a)}}
$('#atlas-search').addEventListener('input',renderSearch);$('#atlas-search').addEventListener('keydown',e=>{if(e.key==='ArrowDown'){e.preventDefault();$('#search-results a')?.focus()}if(e.key==='Enter')$('#search-results a')?.click()});
let expandFeatures=false;function filterFeatures(){const q=$('#feature-filter').value.trim().toLowerCase(),cards=$$('.feature-card');let count=0;cards.forEach(card=>{const match=card.textContent.toLowerCase().includes(q);if(match)count++;card.hidden=!match||(!q&&!expandFeatures&&count>6)});$('#feature-count').textContent=count+' capabilities';$('#feature-expand').hidden=!!q||cards.length<=6;$('#feature-expand').textContent=expandFeatures?'Show the first six capabilities':'Show all '+cards.length+' capabilities'}$('#feature-filter').addEventListener('input',filterFeatures);$('#feature-expand').addEventListener('click',()=>{expandFeatures=!expandFeatures;filterFeatures()});filterFeatures();
document.addEventListener('click',e=>{const source=e.target.closest('[data-source]');if(source){const s=data.sources[source.dataset.source];if(s){e.preventDefault();$('#source-title').textContent=s.symbol||'Source reference';$('#source-location').textContent=s.path+(s.line?':'+s.line:'')+(s.endLine&&s.endLine>s.line?'–'+s.endLine:'');$('#source-code').textContent=s.excerpt;sourceDialog.showModal()}return}const a=e.target.closest('a[href^="#"]');if(a&&a.hash){const target=document.getElementById(decodeURIComponent(a.hash.slice(1)));if(target){e.preventDefault();history.replaceState(null,'',a.hash);reveal(a.hash)}}});
$$('.copy-button').forEach(b=>b.addEventListener('click',async()=>{const text=b.closest('.code-block').querySelector('code').textContent;try{await navigator.clipboard.writeText(text);b.textContent='Copied';setTimeout(()=>b.textContent='Copy',1200)}catch(e){const t=document.createElement('textarea');t.value=text;document.body.append(t);t.select();document.execCommand('copy');t.remove();b.textContent='Copied';setTimeout(()=>b.textContent='Copy',1200)}}));
if('IntersectionObserver'in window){const obs=new IntersectionObserver(entries=>{for(const e of entries)if(e.isIntersecting){$$('.sidebar a').forEach(a=>a.classList.toggle('active',a.hash==='#'+e.target.id))}},{rootMargin:'-12% 0px -70% 0px'});$$('main>.section,main>.document').forEach(s=>obs.observe(s))}
if(location.hash)setTimeout(()=>reveal(location.hash),50);
})();
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    print(json.dumps(Atlas(args.root).build()))


if __name__ == "__main__":
    main()

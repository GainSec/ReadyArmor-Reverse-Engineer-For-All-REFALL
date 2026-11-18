import ast
import os

TEXT_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx", ".md", ".txt", ".json", ".yml",
             ".yaml", ".sh", ".html", ".css", ".cfg", ".toml", ".ini"}
SKIP_DIRS = {".venv", "node_modules", ".git", "__pycache__", ".pytest_cache", "dist", "build"}


def total_lines(src):
    if not src:
        return 0
    return src.count("\n") + (0 if src.endswith("\n") else 1)


def extract_python(src):
    """Top-level symbols only -> non-overlapping by construction (a class is one unit)."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    syms = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            syms.append({"name": node.name, "line_start": node.lineno,
                         "line_end": getattr(node, "end_lineno", node.lineno)})
    return syms


def extract_dir(root, exts=TEXT_EXTS, skip_dirs=SKIP_DIRS):
    """Walk `root`; return [{path(rel), total_lines, symbols[], src}] for every text file."""
    files = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in skip_dirs]
        for fn in fns:
            ext = os.path.splitext(fn)[1].lower()
            if ext not in exts:
                continue
            full = os.path.join(dp, fn)
            rel = os.path.relpath(full, root)
            try:
                src = open(full, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            n = total_lines(src)
            if n == 0:
                continue
            syms = extract_python(src) if ext == ".py" else []
            files.append({"path": rel, "total_lines": n, "symbols": syms,
                          "src": "ast" if ext == ".py" else "file"})
    return files

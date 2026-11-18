import unittest, tempfile, pathlib, json, subprocess, re, base64
from html.parser import HTMLParser

BUILDER = pathlib.Path(__file__).with_name("build_docs.py")


class AtlasContract(unittest.TestCase):
    def test_builds_offline_crosslinked_escaped_atlas(self):
        self.assertTrue(
            BUILDER.exists(), "The standalone documentation builder is not implemented"
        )
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            (root / "docs").mkdir()
            (root / "src").mkdir()
            (root / "docs/assets").mkdir()
            image_bytes = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jM1kAAAAASUVORK5CYII="
            )
            (root / "docs/assets/view.png").write_bytes(image_bytes)
            (root / "README.md").write_text(
                "# Product\n\nPurpose and [configuration](docs/usage.md#configure).\n\n## Repeat\n\nUseful feature.\n\n## Repeat\n\nOther feature.\n"
            )
            with (root / "README.md").open("a") as readme:
                readme.write('\n![Loadout & controls](docs/assets/view.png)\n')
            (root / "docs/usage.md").write_text(
                '# Usage\n\n## Configure\n\nUse `<script>alert(1)</script>` as a literal.\n\n| Setting | Value |\n| --- | --- |\n| Mode | Local |\n\n````text\n```json\n{"value": 1}\n```\n````\n'
            )
            (root / "src/__init__.py").write_text("")
            (root / "src/example.py").write_text(
                'def control():\n    return "</script><script>malicious()</script>"\n'
                + "    # Context line  \n" * 25
                + "    # Selected boundary proof\n"
            )
            source = {
                "path": "src/example.py",
                "symbol": "control",
                "line": 1,
                "endLine": 28,
            }
            profile = {
                "product": "DEMO",
                "name": "Demo Armor",
                "tagline": "An actual product.",
                "summary": "A complete technical atlas.",
                "sourceRoots": ["src"],
                "screenshots": [{
                    "path": "docs/assets/view.png",
                    "title": "Loadout & controls",
                    "kind": "architecture",
                    "category": "Architecture",
                    "alt": 'Loadout with "Hermes" & policy controls',
                    "caption": "Select the armor before launch.",
                }],
                "chapters": [
                    {"path": "README.md", "label": "Overview"},
                    {"path": "docs/usage.md", "label": "Operation"},
                    {"path": "docs/source-index.md", "label": "Source files"},
                ],
                "controlLayers": [
                    {
                        "id": "resource",
                        "title": "Covered resource boundary",
                        "kind": "operation gate",
                        "boundary": "An intercepted operation",
                        "mechanism": "Evaluate the configured deny rule.",
                        "prevents": "Refuse the matching resource request.",
                        "activation": "The interceptor must be installed for this path.",
                        "attempt": "Read the protected example path.",
                        "decision": "Deny before releasing this operation.",
                        "source": [source],
                    },
                    {
                        "id": "guidance",
                        "title": "Task instructions",
                        "kind": "model guidance",
                        "boundary": "The model request",
                        "mechanism": "Supply the stored task instructions.",
                        "prevents": "Explain the authorized task to the model.",
                        "activation": "The request must use the configured adapter.",
                        "attempt": "Consider a different task.",
                        "decision": "Guidance informs the choice; it does not intercept the operation.",
                        "source": [source],
                    },
                ],
                "features": [
                    {
                        "title": "Policy",
                        "description": "Explicit control.",
                        "mechanism": "Examine the request.",
                        "source": [source],
                    }
                ],
                "flows": [
                    {
                        "id": "execution",
                        "title": "Execution",
                        "summary": "A bounded operation.",
                        "diagram": {
                            "nodes": [
                                {"id": "choose", "title": "Select recorded work", "role": "Use the next eligible task.", "layer": "Select", "source": [source]},
                                {"id": "retain", "title": "Retain evidence", "role": "Save observations before the next selection.", "layer": "Persist", "source": [source]},
                            ],
                            "edges": [
                                {"from": "choose", "to": "retain", "label": "dispatch and collect"},
                                {"from": "retain", "to": "choose", "label": "next cycle", "feedback": True},
                            ],
                        },
                        "steps": [
                            {
                                "title": "Check",
                                "detail": "Read policy.",
                                "source": [source],
                            }
                        ],
                    }
                ],
                "architecture": {
                    "nodes": [
                        {
                            "id": "operator",
                            "title": "Operator",
                            "role": "Select the work.",
                            "layer": "Authority",
                            "source": [source],
                        },
                        {
                            "id": "runtime",
                            "title": "Runtime",
                            "role": "Apply the control.",
                            "layer": "Execution",
                            "source": [source],
                        },
                    ],
                    "edges": [
                        {"from": "operator", "to": "runtime", "label": "request"}
                    ],
                },
                "useCases": [
                    {
                        "title": "Research",
                        "description": "Inspect software.",
                        "outcome": "Evidence.",
                    }
                ],
            }
            (root / "docs/site.json").write_text(json.dumps(profile))
            r = subprocess.run(
                ["python3", str(BUILDER), "--root", str(root)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            self.assertTrue(
                (root / "pages/index.html").is_file(),
                "The builder must emit an isolated Pages HTML artifact",
            )
            page = (root / "pages/index.html").read_text()
            self.assertIn(
                "Empty module marker", (root / "docs/source-index.md").read_text()
            )
            self.assertNotIn(
                "__init__.py#L1", (root / "docs/source-index.md").read_text()
            )
            self.assertIn("Demo Armor", page)
            self.assertIn("<table", page)
            self.assertIn("<svg", page)
            self.assertIn("Selected boundary proof", page)
            self.assertTrue(
                all(line == line.rstrip() for line in page.splitlines()),
                "Generated HTML must encode source whitespace without trailing layout whitespace",
            )
            self.assertNotIn("<script>alert(1)</script>", page)
            self.assertNotIn("<script>malicious()</script>", page)
            self.assertIn("application/json", page)
            self.assertIn("Search", page)
            self.assertIn('id="control-in-depth"', page)
            self.assertIn('data-control="control-resource"', page)
            self.assertIn('id="control-guidance"', page)
            self.assertIn("operation gate", page)
            self.assertIn("model guidance", page)
            self.assertIn("The interceptor must be installed for this path.", page)
            self.assertIn(
                "Guidance informs the choice; it does not intercept the operation.",
                page,
            )
            self.assertIn("Configure", page)
            self.assertIn('data-flow="trace-execution"', page)
            self.assertIn('id="inspect-trace-execution"', page)
            self.assertIn('class="graph-edge feedback-edge"', page)
            self.assertIn('"flowNodes"', page)
            self.assertIn("Save observations before the next selection.", page)
            self.assertIn('id="screenshots"', page)
            self.assertIn('id="screenshot-dialog"', page)
            self.assertIn("Select the armor before launch.", page)
            images = re.findall(r'<img\b[^>]*src="(data:image/[^\"]+)"', page)
            self.assertEqual(len(images), 1, "Repeated Markdown images must reuse the gallery asset")
            self.assertIn('data-image-ref="docs/assets/view.png"', page)
            self.assertIn("01 / ARCHITECTURE", page)
            self.assertTrue(all(base64.b64decode(uri.split(",", 1)[1]) == image_bytes for uri in images))
            self.assertEqual((root / "docs/assets/view.png").read_bytes(), image_bytes)
            self.assertIn('alt="Loadout with &quot;Hermes&quot; &amp; policy controls"', page)
            self.assertIn('alt="Loadout &amp; controls"', page)

            class Tags(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.ids = []
                    self.links = []
                    self.network = []
                    self.local_links = []

                def handle_starttag(self, t, attrs):
                    a = dict(attrs)
                    if (
                        t == "a"
                        and a.get("href")
                        and not a["href"].startswith(
                            ("#", "https://", "http://", "mailto:", "data:")
                        )
                    ):
                        self.local_links.append(a["href"])
                    if "id" in a:
                        self.ids.append(a["id"])
                    if t == "a" and a.get("href", "").startswith("#"):
                        self.links.append(a["href"][1:])
                    if (
                        t in ["script", "img", "iframe", "link"]
                        and (a.get("src") or a.get("href"))
                        and not (a.get("src") or a.get("href")).startswith("data:")
                    ):
                        self.network.append(a)

            tags = Tags()
            tags.feed(page)
            self.assertEqual(len(tags.ids), len(set(tags.ids)), "duplicate anchors")
            self.assertTrue(
                all(x in tags.ids for x in tags.links), "broken internal anchors"
            )
            self.assertFalse(tags.network, "The site loads an external asset")
            self.assertFalse(
                tags.local_links,
                "Published navigation must stay within the standalone HTML document",
            )
            self.assertTrue((root / "pages/.nojekyll").exists())
            self.assertEqual(
                {p.name for p in (root / "pages").iterdir()},
                {"index.html", ".nojekyll"},
                "Pages output must contain only the standalone page and its static marker",
            )
            self.assertTrue((root / "docs/usage.md").exists())
            self.assertTrue((root / "docs/site.json").exists())


if __name__ == "__main__":
    unittest.main()

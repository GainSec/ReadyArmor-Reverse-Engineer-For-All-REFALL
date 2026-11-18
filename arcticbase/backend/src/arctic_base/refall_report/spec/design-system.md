# REFALL Report Design System

Reports use self-contained HTML.
Use a restrained layout that makes findings, evidence, and reproduction state easy to examine.

## Required presentation rules

- Make text legible in dark and light deployment themes.
- Wrap long paths and commands in finding tables.
- Keep evidence anchors copyable.
- Identify severity with text as well as color.
- Include the generation timestamp and workbench slug in report metadata.
- Show closeout gate state near the summary with text as well as color.
- Show each pending or deferred action's status, receipt availability, and affected finding or unit.
- For runtime artifacts, show the kind, provenance, available hash, and linked object or path.
- Include visuals only when they help the reviewer.
- Put small diagrams inline when they directly explain the finding or coverage gap.
- Link large graphs and other large assets as workbench objects or load them when their section opens.
- Give each visual a caption, provenance, related evidence identifiers, and a statement of its purpose.

## Visual evidence

Use visual evidence to explain findings and coverage gaps.

Suitable visuals include Graphviz call graphs, dependency graphs, CodeCharta data, Codebadger or Joern slices, and codegraph output.
They can also include screenshots, request or response captures, and exploit or validation flow diagrams.
Preserve the connection between each visual and its supporting evidence.

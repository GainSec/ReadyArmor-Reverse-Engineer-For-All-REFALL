# REFALL AB HTML report specification

This specification applies to individual reports and subject debrief reports.
An individual report examines one finding, artifact, or topic.
A debrief report summarizes the subject, methods, results, and remaining work.

## Layout and packaging

1. Use inline CSS and JavaScript.
2. Keep the report functional when opened as a standalone file.
3. Use workbench theme variables with dark fallback values.
4. Collapse grids to one column below 700 pixels.
5. Put wide tables, code, and SVGs in separate scroll containers.
6. Prevent horizontal scrolling of the page body.
7. Examine the rendered report at widths of 375 and 1280 pixels.

Theme variables include `--wb-bg`, `--wb-surface`, `--wb-ink`, `--wb-muted`, `--wb-rule`, `--wb-accent`, and `--wb-accent-2`.
Radius and shadow variables are `--wb-card-radius` and `--wb-card-shadow`.

Publish HTML objects with `kind:html` and `mime:text/html`.
The default object MIME is `application/octet-stream`.
A wrong MIME can cause a download or an unusable workbench frame.
Recreate an object with the correct MIME when the patch schema cannot change it.
Archive the stale object.

Use working section anchors, workbench object content URLs, or external document links.
Use the configured workbench service URL for object links.
Keep host filesystem paths outside published reports.

## Proof identity

For each retained finding, record:

- The current payload or request name.
- One reproduction command and its expected result.
- The exact supporting artifact names.
- Source paths, functions, lines, or binary offsets.
- The path from attacker input to the affected operation and observable impact.
- Evidence confidence and limitations.

Regenerate the evidence set when the payload changes.
Remove stale alternatives or put them in a clearly identified historical appendix.
Do not combine old screenshots, videos, hashes, paths, or impact statements with current proof.

## Runtime proof

Record the raw command output and observable effect.
For a crash, record the exit status, signal, crash log, and failing frame when available.
For resource exhaustion, record before-and-after measurements and timeout expectations.
For browser injection, record a browser-observed JavaScript effect.
An alert event, relevant DOM mutation, screenshot, video, or DevTools event log can supply that evidence.
Reflected marker text establishes reflection only.

Provide a direct local reproduction command or script with each disclosure package.
The reproduction must not depend on the workbench or compatibility coverage service.
Include a harness service in the archive if reproduction requires that service.

## Evidence package

Include these files and records:

- A README with numbered reproduction steps.
- Proof-of-concept source.
- Raw payload or request files.
- Raw responses and standard output or error output.
- Screenshots or videos for visual claims.
- Crash logs or system diagnosis records when relevant.
- Product, environment, and build provenance.
- Expected output, impact, and remediation information.
- `SHA256SUMS.txt` for the artifact set.

If the archive is encrypted, state its password in the report body.

## Disclosure reports

Identify the vendor, product, component, source or binary identifier, version, architecture, and relevant operating environment.
Record the installation source, default exposure, and applicable target flags.

Give each independent issue its own package.
Combine issues only when the report demonstrates an exploit chain.
The executive report can link the individual packages.

Claim only effects supported by the evidence.
Use precise impact statements for availability, injection, execution, privilege changes, or exposure.
Preserve an unproven chain primitive as `CHAINABLE_DEFERRED`.
Keep that primitive outside the main disclosure body until the missing chain step is proved.

Put limitations in the affected finding's impact section.
Omit internal operator checklists, local service addresses, and stale review counts from disclosure reports.
Use archive-relative artifact names, workbench object URLs, or external vendor documents.
Keep private host paths and temporary harness paths outside the final report.

Place rejected findings, duplicates, and deferred primitives in collapsed sections or outside the disclosure package.

## Publication verification

1. Upload each object with the correct MIME.
2. Read the published object content back from the service.
3. Compare binary package hashes and sizes.
4. Examine the report for stale payload names, hashes, paths, and impact statements.
5. Open the workbench report in a browser.
6. Examine visual proof, section controls, anchors, and links.

## Visual evidence

Use each visual to explain a specific result.
Add a sentence that states what the visual shows.
Keep unreadable graphs outside the main report flow.
Offer raw graph data as an optional linked artifact when useful.

Use an inline SVG for the architecture diagram.
Use labeled arrows, a `viewBox`, and theme colors.
Use summary cards for important measurements.
Define each metric in plain language.

Provide pan, zoom, and reset controls for embedded graphs.
Keep dense graph sections collapsed initially.
Publish graphs larger than 1 MB as separate objects.
Load those graphs on expansion with a same-origin request and a fallback link.
Small graphs below 300 KB can remain inline.

Use collapsible sections, table filters, sorting, tabs, and section navigation where these controls improve reading.
Summarize the subject, languages, scale, and principal complexity concerns.
Explain how agents use the generated indexes.
Keep raw symbol listings and unused links outside the summary.

## Closeout information

Include the closeout gate result, pending actions, runtime evidence, capability decisions, and validation status.
Link the visual evidence pack to its findings.
Read `/api/agent/conventions` for workbench publication conventions.

# Documentation site

The technical atlas contains the product guides, capability catalog, architecture, operating traces, and source excerpts.
All styles, diagrams, scripts, search data, and document content are embedded in `index.html`.
The page works without a product server or an internet connection.

## Open the atlas

Open `pages/index.html` in a browser.
Use the left navigation to select a guide.
Use Search to find a feature, procedure, concept, or implementation symbol.
Use Control in Depth to examine each layer’s boundary, activation, decision scope, and code-path example.
Select a source reference to read its code excerpt.
Use the operating trace tabs to select a campaign cycle, target pass, or resource feedback map.
Select a node to read its behavior and source references.
Dashed return arrows identify later cycles.
Use the color control to select a light or dark theme.
Use the browser print command to print the full technical edition.

## Publication files

The `pages/` directory contains the HTML publication and its static-site marker.
The GitHub Pages workflow uploads this directory.
Markdown guides and build metadata remain in the repository.
The README links both the Markdown guides and the interactive atlas.

## Build the atlas

Run the builder from the repository directory:

```sh
python3 scripts/build_docs.py
```

The builder reads `docs/site.json` and the referenced Markdown chapters.
It refreshes the source file index from the configured implementation directories.
It converts the guides to HTML and embeds the diagrams, search data, and source excerpts.
It writes `pages/index.html` and `pages/.nojekyll`.
The build uses the Python standard library.

Update the Markdown guides when product behavior changes.
Update the site profile when capabilities, operating traces, or source locations change.
Build the atlas after those changes.

## Verify the builder

```sh
python3 -m unittest discover -s scripts -p test_build_docs.py
```

The test checks links, unique anchors, embedded assets, escaped source content, and the isolated publication output.

## Publish with GitHub Pages

1. Push the repository to GitHub.
2. Open the repository settings.
3. Select Pages.
4. Select GitHub Actions as the publishing source.
5. Open Actions.
6. Select Publish documentation.
7. Select Run workflow.
8. Open the site address from the completed deployment.

The workflow builds the atlas and uploads `pages/` as the deployment artifact.
It starts when an operator runs the workflow.
The workflow definition is `.github/workflows/pages.yml`.
See [GitHub Pages workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages) for the publishing settings.

## Share one file

Copy `pages/index.html` to another location or device.
Open the copied file in a browser.
The guides, diagrams, search, operating traces, and source excerpts remain available in that file.

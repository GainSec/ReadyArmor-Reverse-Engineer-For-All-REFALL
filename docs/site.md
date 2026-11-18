# Documentation site

The technical atlas contains the product guides, capability catalog, architecture, operating traces, and source excerpts.
All styles, diagrams, scripts, search data, and document content are embedded in `docs/index.html`.
The page works without a product server or an internet connection.
The repository includes the generated HTML and `docs/.nojekyll` marker.

## Open the atlas

Open [the technical atlas](index.html) in a browser.
Use the left navigation to select a guide.
Use Search to find a feature, procedure, concept, or implementation symbol.
Use Control in Depth to examine each layer's boundary, activation, decision scope, and code-path example.
Select a source reference to read its code excerpt.
Use the operating trace tabs to select a campaign cycle, target pass, or resource feedback map.
Select a node to read its behavior and source references.
Dashed return arrows identify later cycles.
Use the color control to select a light or dark theme.
Use the browser print command to print the full technical edition.

## Publish with GitHub Pages

1. Push the repository's `main` branch to GitHub.
2. Open the repository's **Settings**.
3. Select **Pages**.
4. Under **Build and deployment**, set **Source** to **Deploy from a branch**.
5. Select the `main` branch.
6. Select the `/docs` folder.
7. Select **Save**.
8. After publication completes, select **Visit site**.

GitHub publishes the checked-in HTML from `docs/` when changes reach the selected branch.
The `.nojekyll` marker selects the static publication.
The HTML is already present; publishing does not require a local build.
Read [GitHub's publishing settings](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site) for the repository controls.

## Update the atlas

Update the Markdown guides when product behavior changes.
Update `docs/site.json` when capabilities, operating traces, or source locations change.
Run these commands from the repository directory:

```sh
python3 -m unittest discover -s scripts -p test_build_docs.py
python3 scripts/build_docs.py
```

The builder reads the site profile and referenced Markdown chapters.
It refreshes the generated source file index from the configured implementation directories.
It embeds the guides, diagrams, search data, and source excerpts in `docs/index.html`.
It also creates `docs/.nojekyll` and preserves the hand-authored guides and assets beside the publication.
The build uses the Python standard library.

Commit the updated guides, profile, generated source index, HTML, and static-site marker.
Push those changes to `main` to update the published site.
The builder test checks links, unique anchors, embedded assets, escaped source content, operating traces, and retained source files.

## Share one file

Copy `docs/index.html` to another location or device.
Open the copied file in a browser.
The guides, diagrams, search, operating traces, and source excerpts remain available in that file.

# Diagrams

The images in the README and user manual are pre-rendered SVGs, because
GitHub's live Mermaid renderer fails on some flowcharts ("Could not find a
suitable point for the given distance", mermaid-js/mermaid#6452).

- `src/*.mmd` is the Mermaid source for each diagram. Edit these.
- `<name>.svg` / `<name>-dark.svg` are the light and dark renders.

To update a diagram, edit its `.mmd`, paste it into
[mermaid.live](https://mermaid.live), and export SVG twice, once with the
`default` theme and once with `dark`. Set `htmlLabels: false` in the config
so the SVG has no `<foreignObject>` and renders as a plain image.

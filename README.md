# BER Schema Mapper

A standalone workshop page for mapping classes from BER LinkML schemas onto
high-level grouping classes.

Open [`index.html`](index.html) in any browser (`file://` works). No server, no
build step, no JavaScript dependencies.

Source classes come from the [BRIDGE research dumps](https://github.com/sierra-moxon/bridge-research)
(NMDC, LAMBDA-BER, KBase CDM, BASIN-3D, BERtron, MIAPPE, …). You map each source
class onto a grouping class. The built-in grouping classes follow BASALT’s process
flow, in the same order as the
[schema explorer](https://emsl-computing.github.io/BASALT-Schema/files/schema-explorer.html):

1. Sampling activity
2. Samples
3. Sample processing
4. Processed sample
5. Data generation
6. Data processing
7. Data products

plus **site-specific metadata**, **sample metadata**, and **other / doesn’t fit**.

## How to map

1. Pick a source schema in the left rail.
2. Drag a class onto a grouping class, or click the class and then click the grouping class.
3. Open **BASALT classes** inside a grouping class and drop onto a specific class for a tighter mapping.

On your own, mappings and grouping classes stay in this browser (`localStorage`).
**Export JSON** and **Export CSV** each contain both the mappings and the grouping
classes, from the mapper or from Abstractions. **Import** reads either file and
restores both.

**Deep-link:** `index.html#s=nmdc` opens with that source schema selected.
`index.html#page=groups` opens the grouping-class editor.

Keyboard: `1`–`9` and `0` place the selected class on the original ten grouping classes; `/` focuses search; `Esc` clears the selection.

## Grouping classes

Open **Abstractions** to rename a grouping class or create a new one. An added
grouping class is its own column, marked **Added**, in the color and section you
choose. It has no BASALT subclasses of its own.

Built-in ids stay fixed, so a renamed grouping class keeps the mappings already
saved. The same Export and Import actions are on this page and on the mapper.

## Collaborate

A shared session lets a group edit the same grouping classes and mappings. Each
change is saved and pushed to everyone who has the session open.

```bash
python3 serve.py
```

Open the address it prints (others on the same network can use the network
address). **Share** stays disabled until that server is running. Then enter
your name and **Start a shared session**. Copy the link, or give them the code
to join.

Leave the session when you want a private copy again. The shared copy stays on
the machine running `serve.py`, under `.data/rooms/`, and is still there after
a restart. Opening `index.html` as a file keeps working for one person; sharing
needs the server.

## Updating the catalog

Class lists are embedded in `index.html` so the page works offline. Refresh them
from the BRIDGE dumps with:

```bash
python3 build.py
```

Dumps are cached under `.cache/bridge-dumps/` (gitignored). Delete that folder
to force a re-download.

`build.py` uses the Python standard library only.

## Related

- [BASALT Schema](https://github.com/EMSL-Computing/BASALT-Schema)
- [Schema explorer](https://emsl-computing.github.io/BASALT-Schema/files/schema-explorer.html)
- [BRIDGE research](https://github.com/sierra-moxon/bridge-research)
- [BRIDGE site](https://sierra-moxon.github.io/bridge-research/)

## License

[CC0 1.0 Public Domain Dedication](https://creativecommons.org/publicdomain/zero/1.0/)

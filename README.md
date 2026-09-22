# BASALT Schema Mapper

A standalone workshop page for placing classes from other BER LinkML schemas onto
BASALT’s process abstractions.

Open [`index.html`](index.html) in any browser (`file://` works). No server, no
build step, no JavaScript dependencies.

Source classes come from the [BRIDGE research dumps](https://github.com/sierra-moxon/bridge-research)
(NMDC, LAMBDA-BER, KBase CDM, BASIN-3D, BERtron, MIAPPE, …). Drop targets are
BASALT’s process lanes, matching the
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
2. Drag a class onto a lane, or click the class then click the lane.
3. Open **BASALT classes** inside a lane and drop onto a specific class for a tighter match.

Mappings persist in this browser (`localStorage`) until you **Export JSON** or
**Export CSV**. Import brings a previous export back.

**Deep-link:** `index.html#s=nmdc` opens with that source schema selected.

Keyboard: `1`–`9`/`0` place the selected class on a lane; `/` focuses search; `Esc` clears selection.

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

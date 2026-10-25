# STL → STEP converter (with web dashboard)

Turn STL meshes into **STEP solids** that open cleanly in CAD. Instead of leaving every round feature as a pile of
tiny triangles, the converter recognises **holes, bosses, round bars, cones, domes and rounded edges (fillets)** and
rebuilds them as real curved CAD surfaces, so you do not get mesh lines on them.

It can also hand the result to SolidWorks and save a `.SLDPRT` (Windows + SolidWorks only).

> **Limit:** freeform / organic surfaces (sculpted shapes, scans) are not smoothed. They stay as flat triangles,
> because turning them into smooth surfaces needs NURBS fitting. See [Limitations](#limitations).

---

## Features

- **Curved surface recovery:** cylinders (holes, bosses, bars), cones (countersinks), spheres (domes) and
  tori (rounded edges around holes and bosses) become exact analytic surfaces with true circular edges.
- **Flat faces merged:** thousands of coplanar triangles become one face.
- **Mesh repair first:** fixes flipped triangles and closes holes so you get a **solid**, not a surface.
- **Safe fallbacks:** if a curved face cannot be built exactly, only that face goes back to flat facets. If the whole
  thing fails you still get a valid STEP.
- **Quality report:** *Faceted area* (share of the surface still made of small flat faces) and *Volume match*
  (STEP volume against the mesh).
- **Web dashboard:** drag and drop, 3D preview (enlarge it and it auto-rotates), settings, results, history,
  light / dark / auto theme.
- **Command line** for single files, batches and automation.
- **SolidWorks `.SLDPRT` output** through the SolidWorks API (optional).
- Also reads **OpenSCAD** `.scad` files if OpenSCAD is installed (they are exported to STL first).

---

## Quick start (your own computer)

You need **Python 3.9 to 3.12** (tested on 3.12; the Docker, Codespaces and Actions setups here use 3.11).

```bash
git clone https://github.com/Dhananjay-CAD/STL-TO-Step.git
cd stl-to-step
pip install -r requirements.txt
python dashboard.py          # opens http://localhost:8000
```

On Windows you can double-click **`start_dashboard.bat`**. It checks Python, installs the libraries and starts the
dashboard.

Convert a file without the dashboard:

```bash
python stl2step.py part.stl                  # writes part.step next to it
python stl2step.py *.stl -o out_folder       # batch
python stl2step.py part.scad                 # OpenSCAD file (needs OpenSCAD installed)
```

`requirements.txt` installs `numpy`, `cadquery-ocp` (OpenCascade for Python) and, on Windows only, `pywin32`
(only needed for the SolidWorks option).

**Without numpy / cadquery-ocp** the script still runs in a basic pure-Python mode. It writes a faceted STEP: flat
areas are merged, but curved surfaces stay as triangles.

---

## The dashboard

`python dashboard.py` starts a local web page.

1. **Upload:** drop an STL on the page.
2. **Output format:** *STL → STEP* or *STL → SolidWorks Part (.SLDPRT)*. The SolidWorks card is greyed out unless you
   are on Windows with `pywin32`.
3. **Settings:** recover curved surfaces, repair mesh first, smoothing level, fit tolerance, angle tolerance,
   minimum triangles per surface.
4. **Convert**, then read the result: triangles in, faces out, curved surfaces found, **Faceted area**,
   **Volume match**, a face-type bar, the log, and download buttons. Past conversions are kept in **History**.

**Preview:** drag to rotate. Click **Enlarge** (or double-click the preview) for a large view that
**auto-rotates**; Esc or a click outside closes it. Auto-rotate can be switched off, and it starts off if your system
asks for reduced motion.

Everything runs locally. Results are saved in `dashboard_output/`.

### Settings explained

| Setting | Default | What it does |
|---|---|---|
| Smoothing level | Exact | Presets for the two values below. Higher merges more small triangles into bigger faces: fewer mesh lines, slightly less exact. |
| Fit tolerance | `0.0005` | Fraction of the part size a surface may deviate. Raise it for noisy or scanned meshes. |
| Angle tolerance | `8°` | Largest surface-normal error allowed for a curved fit. |
| Min triangles | `10` | Smallest group of triangles that may become a curved surface. |
| Repair mesh first | on | Fixes flipped triangles and closes holes. |

---

## Command line options

```text
python stl2step.py INPUT [INPUT ...] [options]

  -o, --out FOLDER      output folder (default: next to each input)
  --sldprt              also save a SolidWorks .SLDPRT (Windows + SolidWorks + pywin32)
  --no-curves           skip curved-surface recovery (flat merged faces only)
  --tol FRACTION        fit tolerance as a fraction of part size   (default 0.0005)
  --ang DEGREES         normal tolerance for curved fits            (default 8)
  --min-tris N          minimum triangles per curved surface        (default 10)
  --angle DEGREES       max angle to merge neighbouring flat triangles (default 3)
  --no-repair           do not close holes / fix flipped triangles
  --no-merge            keep every flat triangle as its own face
```

Noisy or scanned mesh? Try `--tol 0.003 --ang 15`.

---

## SolidWorks `.SLDPRT`

`.SLDPRT` is a closed SolidWorks format, so only SolidWorks can write it. `step2sldprt.py` drives SolidWorks on your PC:
it opens the STEP and saves it as `.SLDPRT`.

```bash
pip install pywin32
python step2sldprt.py part.step
python stl2step.py part.stl --sldprt        # convert and save the part in one go
```

Needs Windows with SolidWorks installed and licensed. If it does not work, open the STEP file in SolidWorks
(File → Open → STEP, Options → *Solid/Surface geometry*, tick *Try Form Solid*) and use Save As.

> This part has **not been tested against a real SolidWorks install** by the author. The STEP output itself is tested.

---

## Run it from anywhere (GitHub, cloud)

### A. GitHub Codespaces
Code → **Codespaces** → **Create codespace**. The dashboard starts on port 8000 (open the **Ports** tab if no tab
opens). Codespaces run Linux, so the `.SLDPRT` option is not available; use STEP.

### B. GitHub Actions (no install)
Put STL files in `input/` and commit (this works from the GitHub website, also on a phone). The
**Convert STL to STEP** workflow converts them and uploads a **step-files** artifact you can download from the run.
You can also start it from the **Actions** tab.

### C. Always-on hosting (Render, Railway, Fly.io, ...)
GitHub itself cannot run a live web app. Deploy the included `Dockerfile` to a host and set:

| Variable | Meaning |
|---|---|
| `DASH_PASSWORD` | Password for the dashboard (HTTP Basic login, any user name). **Strongly recommended** on any public address. |
| `MAX_UPLOAD_MB` | Largest upload in MB (default 200). |
| `HOST`, `PORT` | Listen address and port (the Dockerfile sets `0.0.0.0` and `8000`). |
| `NO_BROWSER` | Set to `1` to stop it opening a browser. |

Keep the repo **private** if your parts are confidential.

> The Codespaces, Actions and Docker files are provided as configuration. The converter and the dashboard (including
> password mode) were tested locally; the cloud setups themselves have not been run by the author.

---

## How it works

1. **Read** the STL (binary or ASCII) and weld duplicate vertices.
2. **Repair:** make triangle orientation consistent and close holes (ear clipping, fan fallback), so the mesh is a closed solid.
3. **Find curved surfaces:** a systematic search with robust fitting finds cylinders first, then rounded edges
   (tori around the cylinders' axes), cones and spheres, then leftover cylinder pieces. Each candidate grows over the
   mesh while the triangles stay within tolerance; borders between tangent surfaces are cleaned up.
4. **Flat faces:** remaining triangles are grown into planar faces.
5. **Exact edges:** region borders become straight lines and true circles (or short polylines if neither fits).
6. **Build the solid** with OpenCascade: faces on the fitted surfaces, checked for validity and area, sewn together.
7. **Verify** the volume against the mesh and write the STEP. Anything that fails falls back to flat facets.

---

## Results

Tested on parts modelled in CAD, exported to STL, converted back, and compared with the original solid.

| Test part | Faces out | Volume (STEP vs original) |
|---|---|---|
| Block, 2 holes, countersink, round boss with rounded top edge (about 10,000 triangles) | 12 (3 cylinders, 1 rounded edge, 1 cone, 7 flat) | 62677.22 vs 62677.38; 0 of 6000 test points differ |
| Block with a through hole and a rounded corner | 8 | 46274.69 vs 46274.69 |
| Block, round boss and a sphere dome | 9 | 27939.56 vs 27939.56 |
| Round bar with a cross hole | 4 | 11581.67 vs 11581.59 |
| Block with an angled hole | 7 | 46243.97 vs 46243.80 |
| Block with 4 holes (20,000 triangles) | 10 | 43978.76 vs 43978.76 |

Damaged inputs (random flipped triangles, a hole in the mesh, a whole missing face) are repaired and give the same
result as the clean file. A mesh of about 10,000 triangles takes a few seconds up to about 10 s; larger meshes take
longer.

These are synthetic CAD parts. Real-world files, especially scans, vary.

---

## Limitations

- **Freeform / organic surfaces stay faceted.** Look at **Faceted area** in the dashboard. If it stays high, those areas
  need a NURBS tool (for example Fusion 360 *Convert Mesh → Organic*, SolidWorks *Scan to 3D → Surface Wizard*, or
  Rhino *QuadRemesh* + *ToNURBS*).
- **Noisy / scanned meshes:** curved fits get unreliable; raise `--tol` and `--ang`.
- **Very coarse meshes:** small surfaces made of only a few triangles (for example a countersink cone with a dozen
  facets) can stay as flat facets.
- **Rounded edges (tori)** are only recognised around the axis of a hole, boss or bar that was found first.
- **Mesh must be closable.** Small gaps are repaired; badly damaged meshes fall back to a surface model with a warning.
- **Dashboard takes STL only.** For `.scad`, use the command line.
- The `.SLDPRT` route needs SolidWorks on Windows and is untested by the author.

---

## Troubleshooting

| Problem | Try |
|---|---|
| `pip install cadquery-ocp` fails | Use Python 3.11 or 3.12; run `python -m pip install numpy cadquery-ocp`. |
| Output has many flat faces | Check **Faceted area**. For scans try Smoothing level *Medium* or *High*. |
| Output is a surface, not a solid | Leave **Repair mesh first** on. If it still warns, repair the STL in Meshmixer or 3D Builder. |
| Dashboard does not open | Go to `http://localhost:8000` yourself. If the port is busy it uses the next free one (see the terminal). |
| SolidWorks card is greyed out | Needs Windows, SolidWorks and `pip install pywin32`. |

---

## Project layout

```text
stl2step.py        converter (command line + library)
dashboard.py       local web dashboard
step2sldprt.py     STEP → SolidWorks .SLDPRT (via the SolidWorks API)
start_dashboard.bat  one-click launcher for Windows
requirements.txt   numpy, cadquery-ocp, pywin32 (Windows)
Dockerfile         for hosting the dashboard
input/             drop STL files here for the GitHub Action
.github/workflows/convert.yml   Action: convert everything in input/
.devcontainer/     Codespaces setup
```

---

## License

Add a `LICENSE` file before publishing. The libraries used keep their own licenses (numpy, cadquery-ocp / OpenCascade,
pywin32).

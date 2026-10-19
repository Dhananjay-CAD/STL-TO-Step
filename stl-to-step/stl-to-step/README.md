# STL to STEP / SolidWorks converter

Turns STL meshes into STEP solids. Recovers holes, fillets, bosses, cones and domes as true curved surfaces,
repairs open meshes, and (on Windows with SolidWorks) can save a `.SLDPRT`.

**Limits:** freeform / organic surfaces stay as flat triangles (they need NURBS fitting).

## Use it from anywhere

### A. GitHub Codespaces (easiest, any browser)
1. Push this repo to GitHub (see below).
2. Repo page → green **Code** button → **Codespaces** → **Create codespace on main**.
3. Wait for setup (2–4 min first time). The dashboard opens in a browser tab (port 8000).
   If it doesn't: open the **Ports** tab and click the link for port 8000.
4. Upload an STL, convert, download the STEP. Stop the codespace when done (free plans have monthly hours).

Codespaces run Linux, so the SolidWorks `.SLDPRT` option is not available there; use STEP.

### B. GitHub Actions (no server, no install)
1. Put STL files in the `input/` folder (works from the GitHub website: **Add file → Upload files**, also on a phone).
2. Commit. The **Convert STL to STEP** workflow runs (or run it from the **Actions** tab).
3. Open the finished run and download **step-files**.

### C. Your own computer
```
pip install -r requirements.txt
python dashboard.py            # opens http://localhost:8000
python stl2step.py part.stl    # command line, writes part.step
```
Options: `--tol`, `--ang`, `--no-curves`, `--no-repair`, `-o folder`.

### D. Always-on hosting (Render, Railway, Fly.io, ...)
GitHub itself cannot run a live web app. Deploy this repo's `Dockerfile` to a host and set:
- `DASH_PASSWORD` = a password (**strongly recommended**, the dashboard has no other login)
- optional `MAX_UPLOAD_MB` (default 200)

## Put it on GitHub
```
git init
git add .
git commit -m "STL to STEP converter"
git branch -M main
gh repo create stl-to-step --private --source . --push
```
No GitHub CLI? Create an empty **private** repo on github.com, then:
```
git remote add origin https://github.com/YOUR-NAME/stl-to-step.git
git push -u origin main
```
Keep the repo **private** if your parts are confidential.

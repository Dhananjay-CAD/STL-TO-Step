#!/usr/bin/env python3
"""
step2sldprt.py - Convert STEP files to SolidWorks Part files (.SLDPRT), silently.

SLDPRT is a closed SolidWorks format, so only SolidWorks itself can write it.
This script drives SolidWorks in the BACKGROUND on your PC: no SolidWorks window
is shown, the STEP is opened invisibly, saved as .SLDPRT, closed again, and
SolidWorks is shut down if this script was the one that started it.

Needs: Windows + SolidWorks installed and licensed + pywin32
    pip install pywin32

Usage:
    python step2sldprt.py part.step
    python step2sldprt.py part1.step part2.step
    python step2sldprt.py "C:\\stl\\*.step"
    python step2sldprt.py part.step --show      (only if you WANT to watch SolidWorks)
"""
import glob, os, subprocess, sys

SW_PART, SW_ASSEMBLY = 1, 2  # swDocumentTypes_e


def _solidworks_running():
    """True if a SLDWORKS.exe process (e.g. your own open session) already exists."""
    try:
        import win32com.client
        win32com.client.GetActiveObject("SldWorks.Application")
        return True
    except Exception:
        pass
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq SLDWORKS.exe"],
                             capture_output=True, text=True, timeout=15).stdout
        return "SLDWORKS.exe" in out.upper()
    except Exception:
        return False


def start_solidworks(show=False):
    """
    Return (sw, started_by_us).
    - If SolidWorks is not running: start it and keep it hidden (unless show=True).
    - If you already have SolidWorks open: attach to it and leave your session untouched.
    """
    import win32com.client
    already = _solidworks_running()
    sw = win32com.client.Dispatch("SldWorks.Application")
    if not already:
        try:
            sw.Visible = bool(show)
        except Exception:
            pass
    return sw, (not already)


def release(sw, started_by_us):
    """Close SolidWorks only if we started it. Never closes a session you opened yourself."""
    if not started_by_us:
        return
    try:
        sw.Visible = False
    except Exception:
        pass
    try:
        sw.ExitApp()
    except Exception:
        pass


def _doc_visible(sw, visible):
    """Tell SolidWorks whether documents opened next get a window (False = no window)."""
    for t in (SW_PART, SW_ASSEMBLY):
        try:
            sw.DocumentVisible(bool(visible), t)
        except Exception:
            pass


def convert(sw, step, out, hide=True):
    import pythoncom
    from win32com.client import VARIANT
    err = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warn = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    model = None
    if hide:
        _doc_visible(sw, False)          # open the STEP with no document window
    try:
        imp = None
        try:
            imp = sw.GetImportFileData(step)
        except Exception:
            pass
        model = sw.LoadFile4(step, "", imp, err)
        if model is None:
            raise RuntimeError("SolidWorks could not open the STEP file (error code %s)" % err.value)
        if os.path.exists(out):
            os.remove(out)
        saved = False
        for how in ("ext", "sa3", "sa2"):
            try:
                if how == "ext":
                    saved = bool(model.Extension.SaveAs(out, 0, 1, None, err, warn))
                elif how == "sa3":
                    saved = bool(model.SaveAs3(out, 0, 1))
                else:
                    saved = bool(model.SaveAs2(out, 0, True, False))
                if saved or os.path.exists(out):
                    break
            except Exception:
                continue
    finally:
        if model is not None:
            try:
                sw.CloseDoc(model.GetTitle())
            except Exception:
                pass
        if hide:
            _doc_visible(sw, True)       # restore normal behaviour for your own work
    if not os.path.exists(out):
        raise RuntimeError("SolidWorks opened the file but could not save the .SLDPRT")


def main():
    show = "--show" in sys.argv[1:]
    files = []
    for a in sys.argv[1:]:
        if a.startswith("--"):
            continue
        files += glob.glob(a) or [a]
    files = [f for f in files if f.lower().endswith((".step", ".stp"))]
    if not files:
        sys.exit("Usage: python step2sldprt.py part.step [--show]")
    try:
        import win32com.client  # noqa
    except ImportError:
        sys.exit("pywin32 is missing. Run:  pip install pywin32")
    try:
        sw, started = start_solidworks(show=show)
    except Exception as e:
        sys.exit("Could not start SolidWorks. Is it installed on this PC? (%s)" % e)
    try:
        for f in files:
            f = os.path.abspath(f)
            out = os.path.splitext(f)[0] + ".SLDPRT"
            print("Converting", f)
            try:
                convert(sw, f, out, hide=not show)
                print("  saved", out)
            except Exception as e:
                print("  FAILED:", e)
    finally:
        release(sw, started)


if __name__ == "__main__":
    main()


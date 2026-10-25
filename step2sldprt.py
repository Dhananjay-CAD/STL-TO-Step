#!/usr/bin/env python3
"""
step2sldprt.py - Convert STEP files to SolidWorks Part files (.SLDPRT).

SLDPRT is a closed Dell/SolidWorks format, so only SolidWorks itself can write it.
This script drives SolidWorks on your PC: it opens each STEP and saves it as .SLDPRT.

Needs: Windows + SolidWorks installed and licensed + pywin32
    pip install pywin32

Usage:
    python step2sldprt.py part.step
    python step2sldprt.py part1.step part2.step
    python step2sldprt.py "C:\\stl\\*.step"
"""
import glob, os, sys


def convert(sw, step, out):
    import pythoncom
    from win32com.client import VARIANT
    err = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warn = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
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
    try:
        sw.CloseDoc(model.GetTitle())
    except Exception:
        pass
    if not os.path.exists(out):
        raise RuntimeError("SolidWorks opened the file but could not save the .SLDPRT")


def main():
    files = []
    for a in sys.argv[1:]:
        files += glob.glob(a) or [a]
    files = [f for f in files if f.lower().endswith((".step", ".stp"))]
    if not files:
        sys.exit("Usage: python step2sldprt.py part.step")
    try:
        import win32com.client
    except ImportError:
        sys.exit("pywin32 is missing. Run:  pip install pywin32")
    try:
        sw = win32com.client.Dispatch("SldWorks.Application")
    except Exception as e:
        sys.exit("Could not start SolidWorks. Is it installed on this PC? (%s)" % e)
    sw.Visible = True
    for f in files:
        f = os.path.abspath(f)
        out = os.path.splitext(f)[0] + ".SLDPRT"
        print("Converting", f)
        try:
            convert(sw, f, out)
            print("  saved", out)
        except Exception as e:
            print("  FAILED:", e)


if __name__ == "__main__":
    main()

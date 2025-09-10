# app.py
from fastapi import FastAPI, Request, UploadFile, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sqlmodel import SQLModel, Field, Session, create_engine, select
from typing import Optional
from datetime import datetime
from pathlib import Path
import subprocess
import shutil
import json

# ---------- Paths & folders ----------
ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
IMG_DIR = DATA_DIR / "images"
DB_PATH = DATA_DIR / "oracle.db"

DATA_DIR.mkdir(exist_ok=True)
IMG_DIR.mkdir(parents=True, exist_ok=True)

# ---------- DB model ----------
class Scan(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    image_path: str
    status: str  # "uploaded" | "captured"
    specimen: Optional[str] = None
    captured_at: datetime = Field(default_factory=datetime.utcnow)

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SQLModel.metadata.create_all(engine)

# ---------- FastAPI & templates ----------
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/images", StaticFiles(directory=str(IMG_DIR)), name="images")
templates = Jinja2Templates(directory="templates")

# ---------- Helpers ----------
def _timestamp() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")

def _camera_bin() -> Optional[str]:
    """Prefer modern rpicam-still; fall back to legacy libcamera-still."""
    for name in ("rpicam-still", "libcamera-still"):
        path = shutil.which(name) or f"/usr/bin/{name}"
        if Path(path).exists():
            return path
    return None

def fs_path_to_url(p: Path | str) -> str:
    """Turn a file path inside IMG_DIR into a browser URL under /images/..."""
    p = Path(p)
    return f"/images/{p.name}"

def capture_photo() -> Path:
    """Capture one still from the Pi camera and save to IMG_DIR."""
    ts = _timestamp()
    out_path = IMG_DIR / f"capture_{ts}.jpg"

    cam = _camera_bin()
    if not cam:
        raise RuntimeError(
            "No camera CLI found. Install `rpicam-apps` (or `libcamera-apps`) "
            "and ensure rpicam-still/libcamera-still is on PATH."
        )

    subprocess.run([cam, "-o", str(out_path), "-n", "--timeout", "700"], check=True)
    return out_path

def save_upload(file: UploadFile) -> Path:
    """Save an uploaded file into IMG_DIR with a timestamped name."""
    ts = _timestamp()
    suffix = Path(file.filename).suffix.lower() or ".jpg"
    out_path = IMG_DIR / f"scan_{ts}{suffix}"
    with out_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return out_path

# ---------- Routes ----------
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("home.html", {"request": request})

@app.get("/scan/new", response_class=HTMLResponse)
def scan_new(request: Request):
    return templates.TemplateResponse("scan.html", {"request": request})

@app.post("/scan")
def create_scan(image: UploadFile):
    out_path = save_upload(image)
    with Session(engine) as s:
        rec = Scan(image_path=str(out_path), status="uploaded")
        s.add(rec)
        s.commit()
        s.refresh(rec)
    return RedirectResponse(url=f"/scan/{rec.id}", status_code=303)

@app.post("/capture")
def capture_and_scan():
    try:
        out_path = capture_photo()
    except subprocess.CalledProcessError:
        return HTMLResponse("<h3>Camera capture failed (rpi/libcamera error)</h3>", status_code=500)
    except RuntimeError as e:
        return HTMLResponse(f"<h3>{e}</h3>", status_code=500)

    with Session(engine) as s:
        rec = Scan(image_path=str(out_path), status="captured")
        s.add(rec)
        s.commit()
        s.refresh(rec)

    return RedirectResponse(url=f"/scan/{rec.id}", status_code=303)

@app.get("/scan/{scan_id}", response_class=HTMLResponse)
def scan_show(request: Request, scan_id: int):
    with Session(engine) as s:
        rec = s.get(Scan, scan_id)
        if not rec:
            return HTMLResponse("<h3>Scan not found.</h3>", status_code=404)

    image_url = fs_path_to_url(rec.image_path)
    return templates.TemplateResponse(
        "scan_show.html",
        {"request": request, "scan": rec, "image_url": image_url},
    )

@app.get("/specimens", response_class=HTMLResponse)
def specimens(request: Request):
    data = []
    json_path = DATA_DIR / "specimens.json"
    if json_path.exists():
        with json_path.open("r") as f:
            data = json.load(f)
    return templates.TemplateResponse("specimens.html", {"request": request, "specimens": data})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)


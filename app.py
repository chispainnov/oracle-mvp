from fastapi import FastAPI, Request, UploadFile, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import SQLModel, Field, Session, create_engine, select
from pathlib import Path
from datetime import datetime
from typing import Optional
from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image
import shutil
import subprocess, time
import json
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi import Request

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

DATA_DIR = Path("data"); IMG_DIR = DATA_DIR / "images"
DATA_DIR.mkdir(exist_ok=True); IMG_DIR.mkdir(parents=True, exist_ok=True)
engine = create_engine("sqlite:///data/oracle.db", connect_args={"check_same_thread": False})

class Scan(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    image_path: str
    status: str
    captured_at: datetime = Field(default_factory=datetime.utcnow)

SQLModel.metadata.create_all(engine)

env = Environment(loader=FileSystemLoader("templates"), autoescape=select_autoescape(["html","xml"]))
def render(name, **ctx): return HTMLResponse(env.get_template(name).render(**ctx))

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return render("home.html")

@app.get("/scan/new", response_class=HTMLResponse)
def scan_form(request: Request):
    return render("scan_new.html")

@app.post("/scan")
async def create_scan(image: UploadFile):
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    suffix = Path(image.filename).suffix or ".jpg"
    img_path = IMG_DIR / f"scan_{ts}{suffix}"
    with img_path.open("wb") as f:
        shutil.copyfileobj(image.file, f)
    try:
        im = Image.open(img_path)
        im.thumbnail((800,800))
        im.save(img_path)
    except Exception:
        pass

    with Session(engine) as s:
        scan = Scan(image_path=str(img_path), status="uploaded")
        s.add(scan); s.commit(); s.refresh(scan)
    return RedirectResponse(url=f"/scan/{scan.id}", status_code=303)

@app.get("/scan/{scan_id}", response_class=HTMLResponse)
def scan_detail(scan_id: int):
    with Session(engine) as s:
        scan = s.get(Scan, scan_id)
    return render("scan_show.html", scan=scan)



def capture_photo() -> Path:
    ts = time.strftime("%Y%m%d_%H%M%S")
    out = IMG_DIR / f"capture_{ts}.jpg"
    # Capture one still image from the Pi camera
    subprocess.run(
        ["libcamera-still", "-o", str(out), "-n", "--timeout", "500"],
        check=True
    )
    return out

@app.post("/capture")
def capture_and_scan():
    try:
        img_path = capture_photo()
    except subprocess.CalledProcessError:
        return {"error": "Camera capture failed"}

    # Save this new scan in the database (just like /scan does)
    with Session(engine) as s:
        scan = Scan(image_path=str(img_path), status="captured")
        s.add(scan)
        s.commit()
        s.refresh(scan)

    # Redirect to the scan detail page
    return RedirectResponse(url=f"/scan/{scan.id}", status_code=303)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

with open("data/specimens.json") as f:
    specimens = json.load(f)

@app.get("/specimens")
def list_specimens(request: Request):
    return templates.TemplateResponse("specimens.html",
        {"request": request, "specimens": specimens})

# Optional: make "/" go to the library automatically
@app.get("/")
def home_redirect(request: Request):
    return templates.TemplateResponse("specimens.html",
        {"request": request, "specimens": specimens})

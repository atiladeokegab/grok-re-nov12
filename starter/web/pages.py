"""HTML pages. Designer mockups go in templates/ and read data from the store, nothing else."""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from starter.core.errors import NotFound
from starter.runtime.deps import StoreDep

HERE = Path(__file__).parent
templates = Jinja2Templates(directory=HERE / "templates")
static = StaticFiles(directory=HERE / "static")
router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def home(request: Request, store: StoreDep):
    """The X-ray page (static/index.html) once the front end lands; the runs page until then."""
    index = HERE / "static" / "index.html"
    if index.exists():
        return FileResponse(index)
    return runs_page(request, store)


@router.get("/lease", response_class=HTMLResponse)
def lease_page():
    """The office lease abstractor (static/lease.html, front end's file)."""
    page = HERE / "static" / "lease.html"
    if not page.exists():
        raise NotFound("no lease page yet")
    return FileResponse(page)


@router.get("/runs", response_class=HTMLResponse)
def runs_page(request: Request, store: StoreDep):
    runs = list(reversed(store.snapshot().get("runs", [])))
    status = request.app.state.settings.public()
    return templates.TemplateResponse(request, "runs.html", {"runs": runs, "status": status})

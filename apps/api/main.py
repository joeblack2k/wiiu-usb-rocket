import logging

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from apps.worker.runner import QueueWorker
from core.config import get_settings
from core.db import init_db, init_engine
from core.schemas import DiskAttachRequest, FallbackSettingsRequest, QueueItemCreateRequest
from core.services.catalog_service import CatalogService
from core.services.disk_service import DiskService
from core.services.download_service import DownloadService
from core.services.install_analyzer import InstallAnalyzer
from core.services.queue_service import QueueService
from core.services.settings_service import SettingsService
from core.services.wfs_adapter import WfsAdapterError, build_wfs_adapter
from core.services.writer_engine import WriterEngine

logger = logging.getLogger(__name__)

templates = Jinja2Templates(directory="apps/api/templates")
app = FastAPI(title="Direct Wii U USB Installer", version="1.0.0")


@app.on_event("startup")
def startup() -> None:
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    settings.artifacts_dir.mkdir(parents=True, exist_ok=True)
    settings.simulated_wfs_root.mkdir(parents=True, exist_ok=True)

    if not settings.otp_path.exists():
        logger.warning("Key file missing: %s — attach will fail without it", settings.otp_path)
    if not settings.seeprom_path.exists():
        logger.warning("Key file missing: %s — attach will fail without it", settings.seeprom_path)

    init_engine(settings)
    init_db()

    settings_service = SettingsService(settings)
    settings_service.bootstrap_defaults()

    queue_service = QueueService()
    catalog_service = CatalogService(settings)
    download_service = DownloadService(settings)
    analyzer = InstallAnalyzer()

    wfs_adapter = build_wfs_adapter(settings)
    disk_service = DiskService(settings, wfs_adapter)
    writer_engine = WriterEngine(wfs_adapter, queue_service, settings_service)
    worker = QueueWorker(queue_service, download_service, analyzer, writer_engine, settings_service)

    app.state.settings = settings
    app.state.settings_service = settings_service
    app.state.queue_service = queue_service
    app.state.catalog_service = catalog_service
    app.state.disk_service = disk_service
    app.state.writer_engine = writer_engine
    app.state.worker = worker


@app.on_event("shutdown")
def shutdown() -> None:
    worker: QueueWorker = app.state.worker
    worker.stop()


def get_services(request: Request):
    return {
        "settings": request.app.state.settings,
        "settings_service": request.app.state.settings_service,
        "queue": request.app.state.queue_service,
        "catalog": request.app.state.catalog_service,
        "disk": request.app.state.disk_service,
        "worker": request.app.state.worker,
    }


@app.get("/healthz")
def healthz(request: Request) -> dict:
    services = get_services(request)
    disk = services["disk"].get_active_attachment()
    return {
        "ok": True,
        "worker_running": services["worker"].is_running(),
        "disk_attached": bool(disk),
    }


@app.get("/healthz/details")
def healthz_details(request: Request) -> dict:
    services = get_services(request)
    settings = services["settings"]
    disk = services["disk"].get_active_attachment()

    native_loaded = False
    try:
        import wfs_core_native  # type: ignore  # noqa: F401
        native_loaded = True
    except ImportError:
        pass

    return {
        "ok": True,
        "native_module_loaded": native_loaded,
        "disk_attached": bool(disk),
        "keys_present": {
            "otp": settings.otp_path.exists(),
            "seeprom": settings.seeprom_path.exists(),
        },
        "vault_present": settings.vault_archive_path.exists(),
    }


@app.get("/api/catalog/source")
def api_catalog_source(request: Request) -> dict:
    services = get_services(request)
    return services["catalog"].get_source_status()


@app.get("/api/catalog")
def api_catalog(
    request: Request,
    search: str = "",
    region: str = "",
    category: str = "",
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    services = get_services(request)
    return services["catalog"].query(search=search, region=region, category=category, limit=limit, offset=offset)


@app.post("/api/queue/items")
def api_queue_add(request: Request, payload: QueueItemCreateRequest) -> dict:
    services = get_services(request)
    catalog_item = services["catalog"].lookup(payload.title_id)
    catalog_title = catalog_item.name if catalog_item else None
    return services["queue"].add_item(
        title_id=payload.title_id,
        region=payload.region,
        preferred_mode=payload.preferred_mode.value,
        catalog_title=catalog_title,
    )


@app.get("/api/queue/items")
def api_queue_list(request: Request) -> dict:
    services = get_services(request)
    return {
        "items": services["queue"].list_items(),
        "running": services["worker"].is_running(),
    }


@app.post("/api/queue/start")
def api_queue_start(request: Request) -> dict:
    services = get_services(request)
    services["worker"].start()
    return {"running": True}


@app.post("/api/queue/pause")
def api_queue_pause(request: Request) -> dict:
    services = get_services(request)
    services["worker"].pause()
    return {"running": False}


@app.get("/api/jobs/{job_id}")
def api_job(request: Request, job_id: str) -> dict:
    services = get_services(request)
    job = services["queue"].get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    job["events"] = services["queue"].get_job_events(job_id)
    return job


@app.get("/api/disks/scan")
def api_disks_scan(request: Request) -> dict:
    services = get_services(request)
    payload = services["disk"].scan_devices()
    payload["active"] = services["disk"].get_active_attachment()
    return payload


@app.post("/api/disks/attach")
def api_disks_attach(request: Request, payload: DiskAttachRequest) -> dict:
    services = get_services(request)
    try:
        return services["disk"].attach_device(payload.device_path)
    except WfsAdapterError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/install/{queue_item_id}/execute")
def api_install_execute(request: Request, queue_item_id: str) -> dict:
    services = get_services(request)
    result = services["worker"].execute_queue_item(queue_item_id)
    return {
        "job_id": result.get("job_id"),
        "state": result.get("state", "UNKNOWN"),
    }


@app.post("/api/settings/fallback")
def api_settings_fallback(request: Request, payload: FallbackSettingsRequest) -> dict:
    services = get_services(request)
    value = services["settings_service"].set_bool("allow_fallback", payload.allow_fallback)
    return {"allow_fallback": value}


@app.get("/", response_class=HTMLResponse)
def ui_index(request: Request, search: str = "", region: str = "", category: str = "") -> HTMLResponse:
    services = get_services(request)
    catalog = services["catalog"].query(search=search, region=region, category=category, limit=100, offset=0)
    queue_items = services["queue"].list_items()
    settings = services["settings_service"].get_runtime_settings()
    disk = services["disk"].get_active_attachment()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "catalog": catalog,
            "queue_items": queue_items,
            "worker_running": services["worker"].is_running(),
            "settings": settings,
            "disk": disk,
            "search": search,
            "region": region,
            "category": category,
        },
    )


@app.post("/queue/add")
def ui_queue_add(
    request: Request,
    title_id: str = Form(...),
    region: str = Form("ALL"),
    preferred_mode: str = Form("direct"),
) -> RedirectResponse:
    services = get_services(request)
    catalog_item = services["catalog"].lookup(title_id)
    catalog_title = catalog_item.name if catalog_item else None
    services["queue"].add_item(title_id=title_id, region=region, preferred_mode=preferred_mode, catalog_title=catalog_title)
    return RedirectResponse(url="/", status_code=303)


@app.get("/queue", response_class=HTMLResponse)
def ui_queue(request: Request) -> HTMLResponse:
    services = get_services(request)
    return templates.TemplateResponse(
        request,
        "queue.html",
        {
            "queue_items": services["queue"].list_items(),
            "worker_running": services["worker"].is_running(),
        },
    )


@app.get("/jobs/{job_id}/view", response_class=HTMLResponse)
def ui_job(request: Request, job_id: str) -> HTMLResponse:
    services = get_services(request)
    job = services["queue"].get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return templates.TemplateResponse(
        request,
        "job.html",
        {
            "job": job,
            "events": services["queue"].get_job_events(job_id),
        },
    )


@app.get("/status", response_class=HTMLResponse)
def ui_status(request: Request) -> HTMLResponse:
    services = get_services(request)
    disk_scan = services["disk"].scan_devices()
    return templates.TemplateResponse(
        request,
        "status.html",
        {
            "disk_scan": disk_scan,
            "active_disk": services["disk"].get_active_attachment(),
            "settings": services["settings_service"].get_runtime_settings(),
            "worker_running": services["worker"].is_running(),
            "catalog_source": services["catalog"].get_source_status(),
        },
    )

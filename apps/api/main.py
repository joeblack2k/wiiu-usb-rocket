import logging
import math

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from apps.worker.runner import QueueWorker
from core.config import get_settings
from core.db import init_db, init_engine
from core.schemas import (
    AllowFakeTicketsRequest,
    CommonKeySettingsRequest,
    DiskAttachRequest,
    EnableDownloadsRequest,
    FallbackSettingsRequest,
    QueueItemCreateRequest,
)
from core.services.catalog_service import CatalogService
from core.services.disk_service import DiskService
from core.services.download_service import DownloadService
from core.services.health_service import ReadinessService
from core.services.install_analyzer import InstallAnalyzer
from core.services.queue_service import QueueService
from core.services.settings_service import SettingsService
from core.services.wfs_adapter import WfsAdapterError, build_wfs_adapter
from core.services.writer_engine import WriterEngine

logger = logging.getLogger(__name__)

templates = Jinja2Templates(directory="apps/api/templates")
app = FastAPI(title="Direct Wii U USB Installer", version="1.0.0")


def _configure_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        )
    else:
        root.setLevel(level)


def _build_index_params(
    *,
    search: str,
    region: str,
    category: str,
    starts_with: str,
    page: int,
) -> str:
    params: list[str] = []
    values = {
        "search": search,
        "region": region,
        "category": category,
        "starts_with": starts_with,
    }
    for key, value in values.items():
        if value:
            params.append(f"{key}={value}")
    if page > 1:
        params.append(f"page={page}")
    return "&".join(params)


def _decorate_queue_items(queue_service: QueueService, queue_items: list[dict]) -> list[dict]:
    decorated: list[dict] = []
    for item in queue_items:
        row = dict(item)
        live = {
            "overall_progress": float(item.get("progress", 0.0)),
            "speed_bps": None,
            "current_file": None,
            "file_progress": None,
            "phase_progress": None,
            "updated_at": None,
        }

        latest_job = queue_service.get_latest_job_for_queue_item(item["id"])
        if latest_job is not None:
            row["job_id"] = latest_job["job_id"]

            progress_event = queue_service.get_latest_event(latest_job["job_id"], "download_progress")
            if progress_event is not None:
                payload = progress_event["payload"]
                try:
                    live["overall_progress"] = float(payload.get("overall_progress", live["overall_progress"]))
                except (TypeError, ValueError):
                    pass
                live["speed_bps"] = payload.get("speed_bps")
                live["current_file"] = payload.get("current_file")
                live["file_progress"] = payload.get("file_progress")
                live["phase_progress"] = payload.get("phase_progress")
                live["updated_at"] = progress_event.get("ts")

            stats_event = queue_service.get_latest_event(latest_job["job_id"], "download_stats")
            if stats_event is not None and live["speed_bps"] is None:
                live["speed_bps"] = stats_event["payload"].get("speed_bps")

        row["live_download"] = live
        decorated.append(row)
    return decorated


@app.on_event("startup")
def startup() -> None:
    settings = get_settings()
    _configure_logging(settings.log_level)

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    settings.artifacts_dir.mkdir(parents=True, exist_ok=True)
    settings.simulated_wfs_root.mkdir(parents=True, exist_ok=True)

    if not settings.otp_path.exists():
        logger.warning("Key file missing: %s — attach will fail without it", settings.otp_path)
    if not settings.seeprom_path.exists():
        logger.warning("Key file missing: %s — attach will fail without it", settings.seeprom_path)

    logger.info("startup: nus_base_url=%s log_level=%s", settings.nus_base_url, settings.log_level)

    init_engine(settings)
    init_db()

    settings_service = SettingsService(settings)
    settings_service.bootstrap_defaults()
    settings_service.bootstrap_common_key_env()

    if not settings_service.common_key_present():
        logger.warning(
            "WIIU_COMMON_KEY is not set; encrypted NUS titles cannot be decrypted "
            "(otp.bin/seeprom.bin are USB disk keys only)"
        )

    queue_service = QueueService()
    recovered_jobs = queue_service.recover_incomplete_jobs(reason="startup")
    if recovered_jobs:
        logger.warning("startup: recovered %s interrupted running job(s) as FAILED", recovered_jobs)

    catalog_service = CatalogService(settings)
    download_service = DownloadService(settings)
    analyzer = InstallAnalyzer()

    wfs_adapter = build_wfs_adapter(settings)
    disk_service = DiskService(settings, wfs_adapter)
    if settings.wiiu_disk:
        try:
            disk_service.attach_device(settings.wiiu_disk)
            logger.info("startup: auto-attached WIIU_DISK=%s", settings.wiiu_disk)
        except WfsAdapterError as exc:
            logger.warning("startup: failed to auto-attach WIIU_DISK=%s: %s", settings.wiiu_disk, exc)
    else:
        restored, restore_error = disk_service.restore_runtime_attachment()
        if restored:
            active = disk_service.get_active_attachment() or {}
            logger.info("startup: restored active disk attachment %s", active.get("device_path", "unknown"))
        elif restore_error != "no_active_attachment":
            logger.warning("startup: failed to restore active disk attachment: %s", restore_error)

    readiness_service = ReadinessService(settings, settings_service, disk_service)
    writer_engine = WriterEngine(wfs_adapter, queue_service, settings_service)
    worker = QueueWorker(queue_service, download_service, analyzer, writer_engine, settings_service)

    app.state.settings = settings
    app.state.settings_service = settings_service
    app.state.queue_service = queue_service
    app.state.catalog_service = catalog_service
    app.state.disk_service = disk_service
    app.state.readiness_service = readiness_service
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
        "readiness": request.app.state.readiness_service,
        "worker": request.app.state.worker,
        "writer_engine": request.app.state.writer_engine,
    }


def _readiness_block_response(services: dict) -> JSONResponse | None:
    payload = services["readiness"].evaluate()
    if payload.get("ready"):
        return None
    return JSONResponse(status_code=503, content=payload)


@app.get("/healthz")
def healthz(request: Request) -> dict:
    services = get_services(request)
    disk = services["disk"].get_active_attachment()
    return {
        "ok": True,
        "worker_running": services["worker"].is_running(),
        "disk_attached": bool(disk),
    }


@app.get("/readyz")
def readyz(request: Request) -> dict:
    services = get_services(request)
    payload = services["readiness"].evaluate()
    if payload.get("ready"):
        return payload
    return JSONResponse(status_code=503, content=payload)


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
        "common_key_present": services["settings_service"].common_key_present(),
        "common_key_source": services["settings_service"].common_key_source(),
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
    starts_with: str = "",
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    services = get_services(request)
    return services["catalog"].query(
        search=search,
        region=region,
        category=category,
        starts_with=starts_with,
        limit=limit,
        offset=offset,
    )


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
    items = _decorate_queue_items(services["queue"], services["queue"].list_items())
    return {
        "items": items,
        "running": services["worker"].is_running(),
    }


@app.post("/api/queue/start")
def api_queue_start(request: Request) -> dict:
    services = get_services(request)
    readiness_block = _readiness_block_response(services)
    if readiness_block is not None:
        return readiness_block
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
    readiness_block = _readiness_block_response(services)
    if readiness_block is not None:
        return readiness_block
    result = services["worker"].execute_queue_item(queue_item_id)
    return {
        "job_id": result.get("job_id"),
        "state": result.get("state", "UNKNOWN"),
    }


@app.post("/api/titles/{title_id}/deinstall")
def api_deinstall_title(request: Request, title_id: str) -> dict:
    services = get_services(request)
    try:
        return services["writer_engine"].deinstall_title(title_id)
    except WfsAdapterError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/titles/{title_id}/deinstall")
def ui_deinstall_title(request: Request, title_id: str) -> RedirectResponse:
    services = get_services(request)
    try:
        services["writer_engine"].deinstall_title(title_id)
    except WfsAdapterError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url="/queue", status_code=303)


@app.post("/api/settings/fallback")
def api_settings_fallback(request: Request, payload: FallbackSettingsRequest) -> dict:
    services = get_services(request)
    value = services["settings_service"].set_bool("allow_fallback", payload.allow_fallback)
    return {"allow_fallback": value}


@app.post("/api/settings/downloads")
def api_settings_downloads(request: Request, payload: EnableDownloadsRequest) -> dict:
    services = get_services(request)
    value = services["settings_service"].set_bool("enable_downloads", payload.enable_downloads)
    return {"enable_downloads": value}


@app.post("/api/settings/fake-tickets")
def api_settings_fake_tickets(request: Request, payload: AllowFakeTicketsRequest) -> dict:
    services = get_services(request)
    value = services["settings_service"].set_bool("allow_fake_tickets", payload.allow_fake_tickets)
    return {"allow_fake_tickets": value}


@app.post("/api/settings/common-key")
def api_settings_common_key(request: Request, payload: CommonKeySettingsRequest) -> dict:
    services = get_services(request)
    common_key_hex = payload.common_key_hex.strip()
    try:
        if common_key_hex:
            services["settings_service"].set_common_key(common_key_hex)
        else:
            services["settings_service"].clear_common_key()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "common_key_present": services["settings_service"].common_key_present(),
        "common_key_source": services["settings_service"].common_key_source(),
    }


@app.post("/settings/downloads")
def ui_settings_downloads(
    request: Request,
    enable_downloads: bool = Form(...),
    search: str = Form(""),
    region: str = Form(""),
    category: str = Form(""),
    starts_with: str = Form(""),
    page: int = Form(1),
) -> RedirectResponse:
    services = get_services(request)
    services["settings_service"].set_bool("enable_downloads", enable_downloads)
    params = _build_index_params(
        search=search,
        region=region,
        category=category,
        starts_with=starts_with,
        page=page,
    )
    return RedirectResponse(url=f"/?{params}" if params else "/", status_code=303)


@app.post("/settings/fake-tickets")
def ui_settings_fake_tickets(
    request: Request,
    allow_fake_tickets: bool = Form(...),
    search: str = Form(""),
    region: str = Form(""),
    category: str = Form(""),
    starts_with: str = Form(""),
    page: int = Form(1),
) -> RedirectResponse:
    services = get_services(request)
    services["settings_service"].set_bool("allow_fake_tickets", allow_fake_tickets)
    params = _build_index_params(
        search=search,
        region=region,
        category=category,
        starts_with=starts_with,
        page=page,
    )
    return RedirectResponse(url=f"/?{params}" if params else "/", status_code=303)


@app.post("/settings/common-key")
def ui_settings_common_key(
    request: Request,
    common_key_hex: str = Form(""),
    redirect_to: str = Form("/status"),
) -> RedirectResponse:
    services = get_services(request)
    value = common_key_hex.strip()
    try:
        if value:
            services["settings_service"].set_common_key(value)
        else:
            services["settings_service"].clear_common_key()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    target = redirect_to if redirect_to.startswith("/") else "/status"
    return RedirectResponse(url=target, status_code=303)


@app.get("/", response_class=HTMLResponse)
def ui_index(
    request: Request,
    search: str = "",
    region: str = "",
    category: str = "",
    starts_with: str = "",
    page: int = Query(default=1, ge=1),
) -> HTMLResponse:
    services = get_services(request)

    page_size = 100
    page = max(page, 1)
    offset = (page - 1) * page_size
    catalog = services["catalog"].query(
        search=search,
        region=region,
        category=category,
        starts_with=starts_with,
        limit=page_size,
        offset=offset,
    )

    total_pages = max(1, math.ceil(catalog["total"] / page_size))
    if page > total_pages:
        page = total_pages
        offset = (page - 1) * page_size
        catalog = services["catalog"].query(
            search=search,
            region=region,
            category=category,
            starts_with=starts_with,
            limit=page_size,
            offset=offset,
        )

    queue_items = _decorate_queue_items(services["queue"], services["queue"].list_items())
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
            "starts_with": starts_with,
            "page": page,
            "total_pages": total_pages,
            "page_size": page_size,
            "alphabet": list("ABCDEFGHIJKLMNOPQRSTUVWXYZ") + ["#"],
            "common_key_present": services["settings_service"].common_key_present(),
        "common_key_source": services["settings_service"].common_key_source(),
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


@app.post("/queue/add-bulk")
def ui_queue_add_bulk(
    request: Request,
    sel: list[str] = Form(default=[]),
    preferred_mode: str = Form("direct"),
) -> RedirectResponse:
    services = get_services(request)
    for entry in sel:
        parts = entry.split(":", 1)
        if len(parts) != 2:
            continue
        title_id, region = parts
        catalog_item = services["catalog"].lookup(title_id)
        catalog_title = catalog_item.name if catalog_item else None
        services["queue"].add_item(
            title_id=title_id,
            region=region,
            preferred_mode=preferred_mode,
            catalog_title=catalog_title,
        )
    if sel:
        services["worker"].start()
    return RedirectResponse(url="/queue", status_code=303)


@app.get("/queue", response_class=HTMLResponse)
def ui_queue(request: Request) -> HTMLResponse:
    services = get_services(request)
    queue_items = _decorate_queue_items(services["queue"], services["queue"].list_items())
    return templates.TemplateResponse(
        request,
        "queue.html",
        {
            "queue_items": queue_items,
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
    settings_service = services["settings_service"]
    disk_scan = services["disk"].scan_devices()
    return templates.TemplateResponse(
        request,
        "status.html",
        {
            "disk_scan": disk_scan,
            "readiness": services["readiness"].evaluate(),
            "active_disk": services["disk"].get_active_attachment(),
            "settings": settings_service.get_runtime_settings(),
            "worker_running": services["worker"].is_running(),
            "catalog_source": services["catalog"].get_source_status(),
            "common_key_present": settings_service.common_key_present(),
            "common_key_source": settings_service.common_key_source(),
            "stored_common_key": settings_service.get_stored_common_key(),
        },
    )

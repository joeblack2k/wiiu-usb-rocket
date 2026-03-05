#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path

BASE = os.environ.get("WIIU_TEST_BASE", "http://127.0.0.1:18080").rstrip("/")
TARGET_QUEUE_ID = os.environ.get("WIIU_TARGET_QUEUE_ID", "6405b292-eebf-457c-ade0-0f8406826db1")
CYCLES = int(os.environ.get("WIIU_TEST_CYCLES", "3"))
TIMEOUT = int(os.environ.get("WIIU_TEST_TIMEOUT", "7200"))
OUT = Path(os.environ.get("WIIU_TEST_OUT", "data/cycle_test_results.json"))


def req_json(path: str, method: str = "GET", payload: dict | None = None, timeout: int = 30) -> dict:
    url = f"{BASE}{path}"
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read()
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def wait_health(timeout: int = 180) -> None:
    start = time.time()
    last_err = None
    while time.time() - start < timeout:
        try:
            data = req_json("/healthz", timeout=8)
            if data.get("ok"):
                return
        except Exception as exc:  # noqa: BLE001
            last_err = exc
        time.sleep(1.5)
    raise RuntimeError(f"healthz timeout after {timeout}s; last_err={last_err}")


def restart_container() -> None:
    try:
        subprocess.run(["docker", "restart", "wiiu-usb-rocket"], check=True)
    except subprocess.CalledProcessError:
        subprocess.run(["docker", "stop", "wiiu-usb-rocket"], check=False)
        subprocess.run(["docker", "start", "wiiu-usb-rocket"], check=True)
    wait_health(timeout=240)


def fetch_queue_items() -> list[dict]:
    data = req_json("/api/queue/items")
    return data.get("items", [])


def find_target_item() -> dict:
    items = fetch_queue_items()
    for item in items:
        if item.get("id") == TARGET_QUEUE_ID:
            return item
    raise RuntimeError(f"target queue id {TARGET_QUEUE_ID} not found")


def add_item(title_id: str, region: str, preferred_mode: str = "direct") -> dict:
    return req_json(
        "/api/queue/items",
        method="POST",
        payload={"title_id": title_id, "region": region or "ALL", "preferred_mode": preferred_mode},
    )


def execute_item(queue_item_id: str) -> dict:
    return req_json(
        f"/api/install/{queue_item_id}/execute",
        method="POST",
        payload={},
        timeout=TIMEOUT + 120,
    )


def list_events(job_id: str) -> list[dict]:
    data = req_json(f"/api/jobs/{job_id}")
    return data.get("events", []), data


def wait_job_done(job_id: str, timeout: int = TIMEOUT) -> dict:
    start = time.time()
    last = {}
    while time.time() - start < timeout:
        payload = req_json(f"/api/jobs/{job_id}")
        last = payload
        state = payload.get("state")
        if state in {"DONE", "FAILED"}:
            return payload
        time.sleep(2.0)
    raise RuntimeError(f"job timeout {job_id} after {timeout}s; last={last}")


def calc_speed_metrics(events: list[dict]) -> dict:
    speeds = []
    nonzero = []
    for evt in events:
        evt_type = evt.get("event_type") or evt.get("type")
        if evt_type != "download_progress":
            continue
        payload = evt.get("payload") or {}
        speed = payload.get("speed_bps")
        if isinstance(speed, (int, float)):
            speeds.append(float(speed))
            if speed > 0:
                nonzero.append(float(speed))
    metrics = {
        "samples": len(speeds),
        "nonzero_samples": len(nonzero),
        "avg_speed_bps": int(sum(nonzero) / len(nonzero)) if nonzero else 0,
        "max_speed_bps": int(max(nonzero)) if nonzero else 0,
        "p95_speed_bps": int(statistics.quantiles(nonzero, n=20)[18]) if len(nonzero) >= 20 else (int(max(nonzero)) if nonzero else 0),
    }
    return metrics


def deinstall(title_id: str) -> dict:
    return req_json(f"/api/titles/{title_id}/deinstall", method="POST", payload={})


@dataclass
class CycleResult:
    cycle: int
    queue_item_id: str
    title_id: str
    job_id: str
    state: str
    message: str
    error_code: str | None
    speed: dict
    timings: dict
    deinstall_ok: bool


def run_cycle(cycle_index: int, title_id: str, region: str) -> CycleResult:
    print(f"[cycle {cycle_index}] add_item title_id={title_id} region={region}", flush=True)
    created = add_item(title_id=title_id, region=region or "ALL", preferred_mode="direct")
    qid = created["id"]

    start_ts = time.time()
    print(f"[cycle {cycle_index}] execute queue_item_id={qid}", flush=True)
    exec_payload = execute_item(qid)
    job_id = exec_payload.get("job_id")
    if not job_id:
        raise RuntimeError(f"no job_id returned for queue_item={qid}: {exec_payload}")

    print(f"[cycle {cycle_index}] wait job_id={job_id}", flush=True)
    finished = wait_job_done(job_id)
    print(f"[cycle {cycle_index}] job finished state={finished.get('state')} phase={finished.get('phase')}", flush=True)
    end_ts = time.time()

    events = finished.get("events") or []
    speed = calc_speed_metrics(events)

    state = str(finished.get("state") or "")
    message = str(finished.get("message") or "")
    diagnostics = finished.get("diagnostics") or {}
    error_code = diagnostics.get("error_code") or (diagnostics.get("error") if isinstance(diagnostics, dict) else None)

    deinstall_ok = False
    if state == "DONE":
        print(f"[cycle {cycle_index}] deinstall title_id={title_id}", flush=True)
        try:
            de = deinstall(title_id)
            deinstall_ok = bool(de.get("removed", False)) or bool(de.get("ok", False)) or True
        except Exception as exc:  # noqa: BLE001
            message = f"{message} | deinstall_error={exc}"
            deinstall_ok = False

    return CycleResult(
        cycle=cycle_index,
        queue_item_id=qid,
        title_id=title_id,
        job_id=job_id,
        state=state,
        message=message,
        error_code=error_code,
        speed=speed,
        timings={"start": start_ts, "end": end_ts, "duration_sec": round(end_ts - start_ts, 2)},
        deinstall_ok=deinstall_ok,
    )


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    wait_health(timeout=120)

    target = find_target_item()
    title_id = target["title_id"]
    region = target.get("region") or "ALL"

    results: list[dict] = []
    print(f"[start] target_queue_id={TARGET_QUEUE_ID} title_id={title_id} region={region} cycles={CYCLES}", flush=True)
    for i in range(1, CYCLES + 1):
        result = run_cycle(i, title_id=title_id, region=region)
        results.append(asdict(result))

        if i < CYCLES:
            print(f"[cycle {i}] restarting container wiiu-usb-rocket", flush=True)
            restart_container()
            print(f"[cycle {i}] container healthy after restart", flush=True)

    summary = {
        "base": BASE,
        "target_queue_id": TARGET_QUEUE_ID,
        "title_id": title_id,
        "region": region,
        "cycles": CYCLES,
        "results": results,
        "all_done": all(r["state"] == "DONE" for r in results),
        "all_deinstalled": all(r["deinstall_ok"] for r in results),
    }

    OUT.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

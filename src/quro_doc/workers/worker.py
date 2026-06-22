"""Minimal worker implementation that processes jobs from jobs dir or Redis list."""

import os
import json
import time
from quro_doc.storage import get_storage_root
from quro_doc.storage_layer import StorageLayer
from quro_doc.pipelines.index_pipeline import run_index_pipeline
from quro_doc.pipelines.materialize_pipeline import run_materialize_pipeline_for_assets

def _jobs_dir():
    return os.path.join(get_storage_root(), "jobs")
REDIS_URL = os.getenv("REDIS_URL")
QUEUE_BACKEND = os.getenv("QUEUE_BACKEND", "redis")

def _pop_job_from_redis():
    try:
        if QUEUE_BACKEND == "redis" and REDIS_URL:
            import redis
            r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
            raw = r.rpop("quro_jobs")
            if raw:
                return json.loads(raw)
    except Exception:
        return None
    return None

def _pop_job_from_dir():
    jd = _jobs_dir()
    if not os.path.exists(jd):
        os.makedirs(jd, exist_ok=True)
        return None
    for fname in os.listdir(jd):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(jd, fname)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                job = json.load(fh)
            os.remove(path)
            return job
        except Exception:
            continue
    return None

def process_job(job):
    doc_id = job.get("target_doc") or job.get("doc_id")
    tasks = job.get("task", [])
    if job.get("job_type"):
        tasks = [job["job_type"]]
    project = job.get("_project")
    if project:
        layer = StorageLayer()
        root = layer.resolve_storage_root(project)
        old = os.environ.get("QURO_STORAGE_ROOT")
        os.environ["QURO_STORAGE_ROOT"] = root
        try:
            _run_tasks(doc_id, tasks, job)
        finally:
            if old is not None:
                os.environ["QURO_STORAGE_ROOT"] = old
            else:
                del os.environ["QURO_STORAGE_ROOT"]
    else:
        _run_tasks(doc_id, tasks, job)


def _run_tasks(doc_id: str, tasks: list, job: dict = None):
    if "index" in tasks:
        run_index_pipeline(doc_id)
    if "materialize_asset" in tasks:
        assets = (job or {}).get("payload", {}).get("assets", [])
        run_materialize_pipeline_for_assets(doc_id, assets)

def run_worker(poll_interval=2):
    print("quro worker started")
    while True:
        job = _pop_job_from_redis() or _pop_job_from_dir()
        if job:
            try:
                process_job(job)
            except Exception as e:
                print("Error processing job", e)
        else:
            time.sleep(poll_interval)

"""Run from the repo root with the backend venv:

    backend/.venv/Scripts/python infra/checks/storage_check.py

Not part of `pytest`: these need an emulator running, and the default test run
must not assume one is.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "backend"))

import asyncio
import base64
import os
import tempfile
import uuid

import httpx

os.environ["STORAGE_BACKEND"] = "local"
os.environ["LOCAL_STORAGE_PATH"] = os.path.join(tempfile.gettempdir(), "aiforge-artifacts-check")
os.environ["QUEUE_BACKEND"] = "memory"

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.queue import Event, EventType, reset_queue  # noqa: E402
from app.sandbox.backends import SubprocessBackend  # noqa: E402
from app.sandbox.protocol import ExecutionRequest, TestCase, TestKind  # noqa: E402
from app.storage import get_storage, reset_storage  # noqa: E402
from app.storage.service import figure_key  # noqa: E402

API = "/api/v1"

PLOT_CODE = '''
import matplotlib.pyplot as plt
import numpy as np

def plot_forgetting_curve():
    t = np.linspace(0, 30, 200)
    plt.figure(figsize=(5, 3))
    plt.plot(t, np.exp(-t / 10), label="if you stop")
    plt.axhline(0.9, linestyle="--", label="target")
    plt.legend()
    plt.title("Retention")
    return True
'''


def head(title):
    print()
    print("=" * 74)
    print(title)
    print("=" * 74)


async def main():
    reset_storage()
    reset_queue()

    head("1. THE SANDBOX RETURNS FIGURES (it cannot store them itself)")
    result = await SubprocessBackend().execute(
        ExecutionRequest(
            code=PLOT_CODE,
            tests=[
                TestCase(
                    name="plots",
                    kind=TestKind.PREDICATE,
                    call="plot_forgetting_curve()",
                    predicate="result is True",
                )
            ],
            memory_mb=1024,
            timeout_seconds=40,
        )
    )
    print(f"   status  : {result.status} | passed={result.passed}")
    print(f"   figures : {len(result.figures)}")
    assert result.passed, result.error_message
    assert result.figures, "no figure captured"
    raw = base64.b64decode(result.figures[0]["data"])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    print(f"   PNG     : {len(raw)} bytes, valid header")

    head("2. THE GAME SERVER STORES IT (inline, not on the queue)")
    profile_id = str(uuid.uuid4())
    storage = get_storage()
    key = figure_key(profile_id, "viz-forgetting-curve", raw)
    ref = await storage.put(key, raw, content_type="image/png")
    print(f"   key     : {ref.key}")
    print(f"   url     : {ref.url}")
    stored = await storage.get(key)
    print(f"   stored  : {len(stored) if stored else 0} bytes, identical={stored == raw}")
    assert stored == raw

    head("3. CONTENT ADDRESSING MEANS A REPEAT DOES NOT DUPLICATE")
    from pathlib import Path as _Path

    root = _Path(os.environ["LOCAL_STORAGE_PATH"]) / "figures" / profile_id / "viz-forgetting-curve"
    before = len(list(root.iterdir()))
    await storage.put(key, raw, content_type="image/png")
    await storage.put(figure_key(profile_id, "viz-forgetting-curve", raw), raw)
    after = len(list(root.iterdir()))
    print(f"   objects after 1 write: {before}, after 3: {after}")
    assert before == after == 1, f"content addressing failed: {before} -> {after}"

    head("4. THE CONSUMER RETRIES, THEN DEAD-LETTERS")
    from app.queue.backends import MemoryQueue
    from app.queue.consumer import run_memory_consumer
    from app.queue import consumer as consumer_module

    attempts = []

    async def always_fails(evt):
        attempts.append(evt.attempt)
        raise RuntimeError("handler is broken")

    saved = dict(consumer_module._HANDLERS)
    consumer_module._HANDLERS.clear()
    consumer_module._HANDLERS[EventType.SUBMISSION_GRADED] = [always_fails]
    try:
        queue = MemoryQueue()
        stop = asyncio.Event()
        task = asyncio.create_task(run_memory_consumer(queue, stop))
        await queue.publish(
            Event(type=EventType.SUBMISSION_GRADED, partition_key="p", payload={"profile_id": "p"})
        )
        await asyncio.sleep(1.2)
        stop.set()
        await task
        print(f"   delivery attempts: {attempts}")
        print(f"   dead letters     : {len(queue.dead_letters)}")
        assert attempts == [1, 2, 3], attempts
        assert len(queue.dead_letters) == 1
        print(f"   reason           : {queue.dead_letters[0][1][:60]}")
    finally:
        consumer_module._HANDLERS.clear()
        consumer_module._HANDLERS.update(saved)

    head("5. SERVED OVER HTTP, AND ONLY TO ITS OWNER")
    from app.main import create_app

    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t", timeout=60
    ) as c:
        login = await c.post(
            f"{API}/auth/login",
            json={"identifier": "player@aiforge.dev", "password": "forge-me-2026"},
        )
        headers = {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"}
        me = (await c.get(f"{API}/player/profile", headers=headers)).json()
        real_profile = me["id"]

        # Store one under the real player so it can legitimately be fetched.
        own_key = figure_key(real_profile, "viz-forgetting-curve", raw)
        await get_storage().put(own_key, raw, content_type="image/png")

        ok = await c.get(f"{API}/artifacts/{own_key}", headers=headers)
        print(f"   own artifact      -> {ok.status_code} {ok.headers.get('content-type')}"
              f" {len(ok.content)}B")
        assert ok.status_code == 200 and ok.content == raw

        other = await c.get(f"{API}/artifacts/{key}", headers=headers)
        print(f"   someone else's    -> {other.status_code} (must be 404, not 403)")
        assert other.status_code == 404

        anon = await c.get(f"{API}/artifacts/{own_key}")
        print(f"   unauthenticated   -> {anon.status_code}")
        assert anon.status_code == 401

        traversal = await c.get(f"{API}/artifacts/figures/{real_profile}/../../etc/passwd",
                                headers=headers)
        print(f"   path traversal    -> {traversal.status_code}")
        assert traversal.status_code == 404

        print(f"   cache-control     : {ok.headers.get('cache-control')}")
        print(f"   nosniff           : {ok.headers.get('x-content-type-options')}")

    head("6. BLOB BACKEND AGAINST AZURITE (skipped if not running)")
    conn = (
        "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;"
        "AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;"
        "BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
    )
    os.environ["STORAGE_BACKEND"] = "blob"
    os.environ["BLOB_CONNECTION_STRING"] = conn
    get_settings.cache_clear()
    reset_storage()
    blob = get_storage()
    healthy, detail = await blob.healthcheck()
    print(f"   backend : {blob.name}")
    print(f"   health  : {healthy} - {detail}")
    if healthy:
        blob_key = figure_key(profile_id, "viz-blob", raw)
        ref = await blob.put(blob_key, raw, content_type="image/png")
        fetched = await blob.get(blob_key)
        print(f"   put     : {ref.size_bytes}B -> {ref.url}")
        print(f"   get     : identical={fetched == raw}")
        print(f"   exists  : {await blob.exists(blob_key)}")
        assert fetched == raw
        assert await blob.delete(blob_key) is True
        assert await blob.get(blob_key) is None
        print("   delete  : gone")
        print("   [OK] blob backend verified against Azurite")
    else:
        print("   (Azurite not running - start it to verify this leg)")

    print()
    print("[OK] STORAGE + QUEUE PIPELINE VERIFIED")


asyncio.run(main())

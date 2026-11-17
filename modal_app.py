"""Modal deployment: API + scheduled worker + one-shot backfill/migrate."""

from __future__ import annotations

import modal

APP_NAME = "minuta"
REGION = "ap"
SECRET_NAME = "minuta"

app = modal.App(APP_NAME)

image = (
    modal.Image.debian_slim(python_version="3.13")
    .apt_install("libgomp1")
    .pip_install_from_requirements("requirements.txt")
    .env({"FASTEMBED_CACHE_PATH": "/opt/fastembed"})
    .run_commands(
        "python -c \"from fastembed import TextEmbedding; "
        "TextEmbedding(model_name='BAAI/bge-small-en-v1.5', cache_dir='/opt/fastembed')\""
    )
    .add_local_python_source("src")
    .add_local_dir("migrations", remote_path="/root/migrations")
)

secret = modal.Secret.from_name(SECRET_NAME)


@app.function(image=image, secrets=[secret], region=REGION, timeout=600,
              scaledown_window=300, min_containers=0, max_containers=4)
@modal.asgi_app()
def api():
    from minuta.api import app as fastapi_app

    return fastapi_app


@app.function(image=image, secrets=[secret], region=REGION,
              schedule=modal.Period(minutes=5), timeout=600, max_containers=1)
async def worker_tick() -> dict:
    from minuta.worker import run_tick

    return await run_tick(max_seconds=240)


@app.function(image=image, secrets=[secret], region=REGION, timeout=3600, max_containers=1)
async def backfill(minutes: int = 45) -> dict:
    from minuta.worker import run_tick

    return await run_tick(max_seconds=minutes * 60)


@app.function(image=image, secrets=[secret], region=REGION, timeout=300)
def migrate() -> str:
    import subprocess

    return subprocess.run(["python", "-m", "minuta.migrate"],
                          capture_output=True, text=True, cwd="/root").stdout[-2000:]


@modal.local_entrypoint()
def cli(action: str = "migrate", minutes: int = 20) -> None:
    if action == "migrate":
        print(migrate.remote())
    elif action == "backfill":
        print(backfill.remote(minutes))
    else:
        raise SystemExit(f"unknown action: {action}")

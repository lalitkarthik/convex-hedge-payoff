# Dockerising the development environment

**2026-08-31.** Design approved in conversation; no code written yet.

## Why

Two processes must be started by hand today, in two terminals, after a one-off build:

```
PYTHONPATH=src python scripts/build_runtime.py          # ~50s, once
PYTHONPATH=src python -m uvicorn payoff.api:app --port 8000
cd web && BACKEND_ORIGIN=http://127.0.0.1:8000 bun run dev
```

That works, and it depends on the host having Python 3.13, bun, and every dependency already
installed. This design replaces it with `docker compose up` on a clean machine.

**Purpose: reproducible local development.** Not CI, not deployment. Those are deliberately out
of scope — see *Non-goals*. A second, equal goal is that the author learns Docker while
building this, so the design prefers the plainest construction that still teaches the concept.

## Non-goals

- **Production images.** No multi-stage builds, no `next build`, no registry, no hosting
  target. The design extends into that later by editing two Dockerfiles; nothing here needs
  undoing first.
- **Containerising CI.** GitHub Actions continues to run `pytest` and `ruff` on the host.
- **Splitting `requirements.txt`.** It bundles the notebook stack (jupyterlab, matplotlib) with
  the engine's real dependencies, so the engine image carries a few hundred MB it never
  imports. That is a dependency-layout change, not a Docker one, and dev parity with the host
  environment is a defensible reason to leave it. **Recorded, not fixed.**
- **Fetching the runtime tree from S3.** `.gitignore` says S3 holds it; whether that bucket
  exists was not established.

## Architecture

Two services, one network, one named volume.

```
        docker compose up
                |
    +-----------+-----------+
    |                       |
  engine                   web
  :8000                    :3000
  python:3.13-slim         oven/bun:1
  uvicorn                  next dev
    |                       |
    |   BACKEND_ORIGIN=http://engine:8000
    +<----------------------+
    |
  volume payoff-runtime -> /app/Data/runtime
```

Both services bind-mount the repository, so an edit on the host is live inside the container
with no rebuild. Neither image copies application source; only the dependency manifests are
copied, which is what makes the layer cache useful.

### Files added

All new. No existing file is modified.

| File | Purpose |
|---|---|
| `.dockerignore` | Excludes `node_modules`, `.next`, `.venv`, `Data/runtime`, `__pycache__`, `.git` |
| `Dockerfile.engine` | Python image: dependencies only |
| `Dockerfile.web` | Bun image: dependencies only |
| `docker/engine-entry.sh` | Derives the runtime tree if absent, then execs uvicorn. `chmod +x` in the Dockerfile, because git on Windows does not carry the exec bit |
| `docker-compose.yml` | Wires the two services, ports, volumes and environment |
| `docs/docker.md` | Command cheat-sheet, grown as each concept is met |

`.dockerignore` is load-bearing rather than tidiness: the build context is otherwise ~640 MB
(`web/node_modules` 379 MB, `web/.next` 204 MB, `Data/` 54 MB), and host-built `node_modules`
holds Windows binaries that cannot execute on Linux.

## The engine service

```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt
ENV PYTHONPATH=/app/src
COPY docker/engine-entry.sh /entry.sh
RUN chmod +x /entry.sh
ENTRYPOINT ["/entry.sh"]
```

Dependency manifests are copied before anything else so that editing Python source invalidates
no layer and rebuilds in about a second. Only a change to `requirements*.txt` re-runs `pip`.

### Runtime tree bootstrap

The engine refuses to start without `Data/runtime/`, and raises naming the command rather than
re-deriving silently. That behaviour is preserved; the entrypoint simply satisfies it first.

```sh
#!/bin/sh
set -e

MANIFEST=/app/Data/runtime/manifest_v1/part-0.parquet

if [ ! -f "$MANIFEST" ]; then
  echo "runtime tree absent - deriving 24 dates (about 50s, once)"
  python scripts/build_runtime.py
fi

if [ "$RUNTIME_CHECK" = "1" ]; then
  python scripts/build_runtime.py --check
fi

exec uvicorn payoff.api:app --host 0.0.0.0 --port 8000
```

Four decisions in that script:

- **Test for the manifest, not for the directory.** `scripts/build_runtime.py` documents
  `manifest_v1/part-0.parquet` as *"written last, from the tree"*. It is the project's own
  completion marker, so its presence means the derivation finished. A directory test would pass
  on a tree that was interrupted half-written.
- **`--check` is opt-in, behind `RUNTIME_CHECK=1`, and is not the startup path.** This was
  wrong in an earlier draft. `check()` re-derives every trading date in order to reconcile it,
  so calling it at boot would pay the full ~50s on *every* start rather than the first. Its own
  docstring says it is what CI runs. It stays available for when a stale tree is suspected.
- **`--host 0.0.0.0`.** Bound to `127.0.0.1` the server is reachable only from inside its own
  container. This is the most common "the container is running but I cannot reach it" fault.
- **`exec`.** Replaces the shell with uvicorn so that `SIGTERM` reaches the server directly.
  Without it `docker compose stop` waits out its ten-second grace period on every stop.

**Known gap this accepts:** a tree derived by older code is not detected at boot. That is the
existing behaviour on the host too — the engine reads whatever tree it finds — and `RUNTIME_CHECK=1`
is the deliberate way to ask. Detecting staleness cheaply would need a code version stamped
into the manifest, which is a change to the project rather than to Docker.

The tree lands in the named volume `payoff-runtime`, so the ~50s cost is paid once and survives
rebuilds. It is 11 MB — the cost is compute, not space.

## The web service

```dockerfile
FROM oven/bun:1
WORKDIR /app
COPY web/package.json web/bun.lock ./
RUN bun install
CMD ["bun", "run", "dev", "--", "-H", "0.0.0.0"]
```

### The node_modules masking volume

Bind-mounting `web/` would carry the host's 379 MB `node_modules` into the container. Two
independent failures follow: every module read crosses the Windows/Linux filesystem boundary,
turning a 4-second Next.js compile into a minute or more; and packages with compiled binaries
were built for Windows and will not run on Linux.

An anonymous volume masks the path:

```yaml
volumes:
  - ./web:/app            # source, live
  - /app/node_modules     # anonymous: keeps the image's Linux modules
```

The second entry has no host side. It shadows whatever the first mount put at that path, so the
container uses the `node_modules` produced by `bun install` during the build.

## Compose

```yaml
services:
  engine:
    build: { context: ., dockerfile: Dockerfile.engine }
    ports: ["8000:8000"]
    volumes:
      - .:/app
      - payoff-runtime:/app/Data/runtime

  web:
    build: { context: ., dockerfile: Dockerfile.web }
    ports: ["3000:3000"]
    volumes:
      - ./web:/app
      - /app/node_modules
    environment:
      BACKEND_ORIGIN: http://engine:8000
    depends_on: [engine]

volumes:
  payoff-runtime:
```

`BACKEND_ORIGIN` changes from `http://127.0.0.1:8000` to **`http://engine:8000`**. Compose runs
an embedded DNS server on the default network, so a service name resolves to that service's
container. No IP address is ever written down.

`depends_on` orders startup only; it does not wait for the engine to be ready. The frontend
proxies on request rather than at boot, so the first page load may be the thing that waits.
**If that proves flaky in practice, add a healthcheck** — not before.

## Error handling

| Failure | Behaviour |
|---|---|
| Runtime tree missing | Entrypoint derives it, printing that it will take ~50s |
| Runtime tree half-written | Manifest absent (it is written last), so the tree is rebuilt |
| Runtime tree stale | **Not detected at boot** by design; `RUNTIME_CHECK=1` reconciles on demand |
| `build_runtime.py` raises | `set -e` aborts; container exits non-zero; `docker compose logs engine` shows the real error |
| Engine not yet up when a page loads | Frontend proxy errors on that request; retry succeeds |

## Verification

The acceptance bar is the path driven manually on 2026-08-31, reproduced with identical
numbers:

1. `docker compose up` on a tree with no `Data/runtime/` — engine derives it, both services start.
2. `http://localhost:3000` renders the Chain for 2026-01-27, expiry 10FEB26.
3. Clicking **straddle** builds two legs at 25,200 — CE at 344.05, PE at 326.7.
4. **Analyse** draws the payoff chart and reports:

```
Max profit    Unlimited
Max loss        -670.75
Breakevens    24,529.25 - 25,870.75
Net premium      670.75 debit
```

5. Editing a `.py` file under `src/` reloads the engine without a rebuild.
6. Editing a `.tsx` file under `web/` reloads the page without a rebuild.
7. `docker compose down && docker compose up` completes in seconds — the volume persists, so
   the tree is not rederived.

Any change to the numbers in step 4 means the containerised engine is not reading what the host
engine read, and is a defect rather than a tolerance.

Existing test suites are unaffected and continue to run on the host.

## Teaching order

Each concept is introduced at the step that requires it. Nothing is taught ahead of need.

| Build step | Concept | Commands met |
|---|---|---|
| First `docker build` | image vs container | `build`, `images`, `ps -a` |
| Second build | layers, the build cache | `history` |
| First `compose up` | services, networks, service DNS | `up`, `down`, `logs -f` |
| Engine bootstraps | named volumes vs bind mounts | `volume ls`, `volume rm` |
| Something fails | inspecting a running container | `exec -it`, `inspect` |

`docs/docker.md` accumulates these as they are met, rather than being written up front.

## Prerequisite

**Docker Desktop is not installed on the development machine** (`docker: command not found`).
Installation, including the WSL2 backend and a restart, precedes any of this work.

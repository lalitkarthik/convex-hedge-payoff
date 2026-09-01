# Dockerised Development Environment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the three-command manual startup with `docker compose up`, on a machine that has only Docker installed.

**Architecture:** Two containers — a Python engine and a bun frontend — on one Compose network. Neither image copies application source; the repository is bind-mounted so edits are live. The derived runtime tree lives in a named volume, built once by the engine's entrypoint. An anonymous volume masks the host's `node_modules` so the container uses Linux-built packages.

**Tech Stack:** Docker 29.7.2, Compose v2, `python:3.13-slim`, `oven/bun:1`, uvicorn, Next.js 15.

**Spec:** [`docs/superpowers/specs/2026-08-31-dockerize-dev-environment-design.md`](../specs/2026-08-31-dockerize-dev-environment-design.md)

## Global Constraints

- **Repository:** `D:\Convex Hedge\payoff-project`, currently on `main` at `56b5dbe`.
- **Work on a branch.** `feat/dockerise-dev-environment`. Never commit to `main`.
- **`docker` is not on the PATH of an already-open shell.** It is at
  `C:\Users\Acer\AppData\Local\Programs\DockerDesktop\resources\bin`, which *is* on the user
  PATH — a newly opened terminal resolves `docker` normally. In a stale shell, use the full
  path. Every command below is written as plain `docker`.
- **Modify no existing file.** Every file in this plan is new. If a task appears to require
  editing project source, stop and report it.
- **Base images are pinned to a major:** `python:3.13-slim` and `oven/bun:1`. Do not use
  `latest`.
- **Servers must bind `0.0.0.0`,** never `127.0.0.1`.
- **Acceptance numbers, from the manual run on 2026-08-31.** The 25,200 straddle on
  2026-01-27, expiry 10FEB26, must report: max loss **−670.75**, breakevens
  **24,529.25 · 25,870.75**, net premium **670.75 debit**. These are exact, not approximate.
- **`docs/docker.md` grows task by task.** Each task appends the commands it introduced. Do not
  write it up front.
- **Do not run `docker system prune`.** It removes images belonging to other work.

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `.dockerignore` | Keeps the build context small and excludes host-built artefacts | 1 |
| `Dockerfile.engine` | Python dependency layer for the engine | 1 |
| `docker/engine-entry.sh` | Derives the runtime tree if absent, then execs uvicorn | 2 |
| `Dockerfile.web` | Bun dependency layer for the frontend | 3 |
| `docker-compose.yml` | Wires both services, ports, volumes, environment | 4 |
| `docs/docker.md` | Command cheat-sheet, appended to by tasks 1–4 | 1–4 |

There is no test-suite change. The existing `pytest` and `ruff` runs are unaffected and stay on
the host.

**On testing in this plan:** these are infrastructure artefacts, so the test cycle is a Docker
command with a predicted result rather than a unit test. Every task still follows
predict → run → verify → commit, and every verification below states the exact expected output.

---

### Task 0: Branch

**Files:** none.

- [ ] **Step 1: Confirm the starting point**

```bash
cd "D:/Convex Hedge/payoff-project"
git status --short --branch
```

Expected: `## main...origin/main`, and an untracked `docs/handoff.md` plus `docs/superpowers/`.
The untracked `docs/handoff.md` is someone else's work — **do not stage it at any point.**

- [ ] **Step 2: Create the branch**

```bash
git checkout -b feat/dockerise-dev-environment
```

Expected: `Switched to a new branch 'feat/dockerise-dev-environment'`

- [ ] **Step 3: Commit the spec and this plan**

```bash
git add docs/superpowers/specs/2026-08-31-dockerize-dev-environment-design.md
git add docs/superpowers/plans/2026-08-31-dockerize-dev-environment.md
git commit -m "docs: design and plan for a dockerised dev environment

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 1: Build context and the engine image

**Files:**
- Create: `.dockerignore`
- Create: `Dockerfile.engine`
- Create: `docs/docker.md`

**Interfaces:**
- Consumes: nothing.
- Produces: an image tagged `payoff-engine:dev`, with every dependency from
  `requirements.txt` and `requirements-dev.txt` installed, `WORKDIR /app`, and
  `PYTHONPATH=/app/src`. Task 2 adds an entrypoint to this same Dockerfile.

- [ ] **Step 1: Write `.dockerignore`**

Create `.dockerignore` at the repository root:

```
.git
.venv
__pycache__
**/__pycache__
*.pyc
.ipynb_checkpoints
Data/runtime
web/node_modules
web/.next
web/tsconfig.tsbuildinfo
notebooks
docs
```

Every line earns its place. `web/node_modules` is 379 MB of Windows binaries that cannot run on
Linux. `web/.next` is 204 MB of stale build output. `Data/runtime` is derived and belongs in a
volume. `.git` is history the image never reads.

`Data/` itself is **deliberately absent** from this list — the engine derives the runtime tree
from it, and it arrives by bind mount rather than by copy.

- [ ] **Step 2: Write `Dockerfile.engine`**

Create `Dockerfile.engine` at the repository root:

```dockerfile
FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt

ENV PYTHONPATH=/app/src

CMD ["python", "-c", "import payoff; print('engine image OK')"]
```

The `CMD` is a placeholder that Task 2 replaces with an entrypoint. It exists so this task has
something to verify on its own.

- [ ] **Step 3: Build the image**

```bash
docker build -f Dockerfile.engine -t payoff-engine:dev .
```

Expected: the first line reads roughly `transferring context: 55MB` — **not** 600 MB. If it
shows hundreds of megabytes, `.dockerignore` is not being read; check it is at the repository
root and spelled exactly.

Expected: ends `naming to docker.io/library/payoff-engine:dev`. Takes 2–4 minutes; `pip` is
installing the notebook stack as well as the engine's own dependencies.

- [ ] **Step 4: Verify the image exists, and see the image/container distinction**

```bash
docker images payoff-engine
docker ps -a
```

Expected: `docker images` lists one row, `payoff-engine  dev  <id>  ...`. Expected:
`docker ps -a` shows **no container** for it.

That pair is the concept: the image exists, and nothing is running. An image is a recipe; a
container is one execution of it.

- [ ] **Step 5: Run a container from it**

```bash
docker run --rm -v "D:/Convex Hedge/payoff-project:/app" payoff-engine:dev
```

Expected output: `engine image OK`

This proves three things at once: the dependencies installed, the bind mount delivered `src/`,
and `PYTHONPATH` is right. `--rm` deletes the container when it exits, which is why `docker ps -a`
stays clean.

- [ ] **Step 6: Demonstrate the layer cache**

```bash
docker build -f Dockerfile.engine -t payoff-engine:dev .
```

Expected: every step reads `CACHED`, and the build finishes in **under 2 seconds**.

Now touch a source file and rebuild:

```bash
touch src/payoff/api.py
docker build -f Dockerfile.engine -t payoff-engine:dev .
```

Expected: still fully `CACHED`, still under 2 seconds. Nothing reinstalled, because the
Dockerfile copies only `requirements*.txt` — a change to `src/` cannot invalidate the `pip`
layer. This is why the dependency manifests are copied first.

- [ ] **Step 7: Start the cheat-sheet**

Create `docs/docker.md`:

````markdown
# Docker, as used in this project

Written while dockerising the dev environment. Each section was added when the
command was first needed.

## Images and containers

An **image** is a built filesystem plus a default command. A **container** is one
running instance of an image. Images are reusable; containers are disposable.

```bash
docker build -f Dockerfile.engine -t payoff-engine:dev .   # build an image
docker images                                              # list images
docker ps                                                  # running containers
docker ps -a                                               # all, including exited
docker run --rm IMAGE                                      # run, delete on exit
```

`-t` names the image. `-f` selects the Dockerfile. The trailing `.` is the **build
context** — the directory sent to the daemon, filtered by `.dockerignore`.

## The build context

Everything in the context is uploaded before the build starts. Ours is ~55 MB. Without
`.dockerignore` it would be ~640 MB, because `web/node_modules` is 379 MB and
`web/.next` is 204 MB.

Those two must be excluded for a second reason: they were built on Windows, and the
container is Linux.

## Layers and the cache

Each Dockerfile instruction makes a layer. Docker reuses a layer when neither the
instruction nor its inputs changed, and invalidates every layer after the first change.

This is why dependency manifests are copied before source:

```dockerfile
COPY requirements.txt requirements-dev.txt ./   # changes rarely
RUN pip install ...                             # slow - stays cached
```

Editing a `.py` file rebuilds in under 2 seconds. Editing `requirements.txt` re-runs
`pip`. Copying the source before the install would make every edit a full reinstall.

```bash
docker history payoff-engine:dev    # the layers, and what each cost
```
````

- [ ] **Step 8: Commit**

```bash
git add .dockerignore Dockerfile.engine docs/docker.md
git commit -m "feat(docker): engine image and a minimal build context

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: The entrypoint, and the engine serving

**Files:**
- Create: `docker/engine-entry.sh`
- Modify: `Dockerfile.engine` (replace the placeholder `CMD` with an `ENTRYPOINT`)
- Modify: `docs/docker.md` (append two sections)

**Interfaces:**
- Consumes: `payoff-engine:dev` from Task 1, and `PYTHONPATH=/app/src`.
- Produces: a container that serves the engine on port 8000 and populates
  `/app/Data/runtime` if the manifest is absent. Task 4 runs this as the `engine` service.

- [ ] **Step 1: Write the entrypoint**

Create `docker/engine-entry.sh`. **Write it with LF line endings** — a CRLF shell script fails
with `bad interpreter: /bin/sh^M`, which is a confusing error for an obvious cause.

```sh
#!/bin/sh
set -e

MANIFEST=/app/Data/runtime/manifest_v1/part-0.parquet

if [ ! -f "$MANIFEST" ]; then
  echo "runtime tree absent - deriving 24 dates (about 50s, once)"
  python scripts/build_runtime.py
fi

if [ "$RUNTIME_CHECK" = "1" ]; then
  echo "reconciling the stored tree against a fresh derivation"
  python scripts/build_runtime.py --check
fi

exec uvicorn payoff.api:app --host 0.0.0.0 --port 8000
```

Why each part, since all four are load-bearing:

- **The manifest test, not a directory test.** `scripts/build_runtime.py` documents
  `manifest_v1/part-0.parquet` as *"written last, from the tree"*. Its presence means the
  derivation completed. A directory test would pass on an interrupted, half-written tree.
- **`--check` behind `RUNTIME_CHECK=1`, never by default.** `check()` re-derives every trading
  date to reconcile it, so running it at boot would cost ~50s on *every* start.
- **`--host 0.0.0.0`.** On `127.0.0.1` the server is reachable only from inside its own
  container, and `curl` from the host would fail while the logs looked healthy.
- **`exec`.** Replaces the shell with uvicorn so `SIGTERM` reaches the server. Without it,
  `docker compose stop` waits out a ten-second grace period every time.

- [ ] **Step 2: Point the Dockerfile at it**

In `Dockerfile.engine`, replace the placeholder `CMD` line with:

```dockerfile
COPY docker/engine-entry.sh /entry.sh
RUN chmod +x /entry.sh
ENTRYPOINT ["/entry.sh"]
```

The `chmod` is required: git on Windows does not preserve the executable bit, so the copied
file arrives non-executable and the container would exit with `permission denied`.

- [ ] **Step 3: Rebuild**

```bash
docker build -f Dockerfile.engine -t payoff-engine:dev .
```

Expected: the `pip install` layer reads `CACHED`; only the two new instructions run. Under 10
seconds.

- [ ] **Step 4: Create the volume and run the engine**

```bash
docker volume create payoff-runtime
docker run --rm -p 8000:8000 \
  -v "D:/Convex Hedge/payoff-project:/app" \
  -v payoff-runtime:/app/Data/runtime \
  --name payoff-engine payoff-engine:dev
```

Expected, in order:

1. `runtime tree absent - deriving 24 dates (about 50s, once)` — the named volume starts empty,
   masking the host's populated `Data/runtime`.
2. About 50 seconds of silence.
3. `Uvicorn running on http://0.0.0.0:8000`

Leave it running for the next step.

- [ ] **Step 5: Verify it serves, from outside the container**

In a second terminal:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/docs
```

Expected: `200`

`-p 8000:8000` is what makes this work. The left number is the host, the right is inside the
container; without the flag the port is not published and this returns nothing.

- [ ] **Step 6: Prove the volume persists the tree**

Stop the container with Ctrl-C, then run the identical command from Step 4 again.

Expected: **no derivation message**, and `Uvicorn running` within a few seconds. The manifest
is in the volume, so the tree is not rebuilt. This is the difference between a named volume and
a container's own filesystem, which is discarded on `--rm`.

Stop it again with Ctrl-C.

- [ ] **Step 7: Append to the cheat-sheet**

Append to `docs/docker.md`:

````markdown
## Entrypoints, and stopping cleanly

A container runs one command. When more than one thing must happen, put them in a
script and make the script that command.

```dockerfile
COPY docker/engine-entry.sh /entry.sh
RUN chmod +x /entry.sh          # git on Windows drops the executable bit
ENTRYPOINT ["/entry.sh"]
```

End the script with `exec`:

```sh
exec uvicorn payoff.api:app --host 0.0.0.0 --port 8000
```

`exec` replaces the shell with uvicorn, so the container's main process *is* the server.
Docker's stop signal then reaches it directly. Without `exec` the signal goes to the
shell, which ignores it, and Docker waits ten seconds before killing the container.

## Ports

```bash
docker run -p 8000:8000 IMAGE     # host 8000 -> container 8000
```

Two separate numbers that usually match. Publishing is not enough on its own: the
server inside must also bind `0.0.0.0`. Bound to `127.0.0.1` it only accepts
connections from inside its own container, and the logs look perfectly healthy while
nothing outside can reach it.

## Volumes

```bash
docker volume create payoff-runtime
docker volume ls
docker volume rm payoff-runtime         # force the tree to rebuild
docker run -v payoff-runtime:/app/Data/runtime IMAGE     # named volume
docker run -v "D:/path:/app" IMAGE                       # bind mount
```

A **bind mount** shows a host directory inside the container — used here for source, so
edits are live. A **named volume** is storage Docker owns; it survives `--rm` and
rebuilds, and is where derived data belongs.

A mount **masks** whatever is beneath it. The empty `payoff-runtime` volume hides the
host's populated `Data/runtime`, which is why the first run derives the tree even
though the host already has one.
````

- [ ] **Step 8: Commit**

```bash
git add docker/engine-entry.sh Dockerfile.engine docs/docker.md
git commit -m "feat(docker): entrypoint derives the runtime tree, then serves

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: The frontend image

**Files:**
- Create: `Dockerfile.web`
- Modify: `docs/docker.md` (append one section)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: an image tagged `payoff-web:dev` with `WORKDIR /app`, Linux-built
  `node_modules` at `/app/node_modules`, and a default command that starts `next dev` bound to
  `0.0.0.0`. Task 4 runs this as the `web` service.

- [ ] **Step 1: Write `Dockerfile.web`**

Create `Dockerfile.web` at the repository root:

```dockerfile
FROM oven/bun:1

WORKDIR /app

COPY web/package.json web/bun.lock ./
RUN bun install --frozen-lockfile

CMD ["bun", "run", "dev", "--", "-H", "0.0.0.0"]
```

The `COPY` paths are `web/`-prefixed because the build context is the repository root, which
Task 4's Compose file also relies on. `--frozen-lockfile` makes the build fail rather than
silently resolve different versions than `bun.lock` records.

- [ ] **Step 2: Build it**

```bash
docker build -f Dockerfile.web -t payoff-web:dev .
```

Expected: ends `naming to docker.io/library/payoff-web:dev`. Under a minute.

- [ ] **Step 3: Verify the packages are Linux-built and present**

```bash
docker run --rm payoff-web:dev sh -c "ls node_modules | wc -l && uname -s -m"
```

Expected: a count in the hundreds, then `Linux x86_64`.

That second line is the point. The host's `node_modules` holds Windows binaries; these were
resolved and installed for Linux inside the image.

- [ ] **Step 4: Verify the dev server binds 0.0.0.0**

```bash
docker run --rm -p 3000:3000 \
  -v "D:/Convex Hedge/payoff-project/web:/app" \
  -v /app/node_modules \
  payoff-web:dev
```

Expected: Next.js starts and prints a `Network:` line — that line only appears when it is bound
beyond localhost.

In a second terminal:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000/
```

Expected: `200`. The first request compiles the page, so allow up to 60 seconds; use
`curl -m 90`.

**If it does not bind 0.0.0.0** — no `Network:` line, or curl returns nothing — the `--`
argument forwarding through `bun run` is the cause. Change the last line of `Dockerfile.web` to
bypass the script:

```dockerfile
CMD ["bunx", "next", "dev", "-H", "0.0.0.0"]
```

Rebuild and repeat this step.

Stop the container with Ctrl-C.

- [ ] **Step 5: Append to the cheat-sheet**

Append to `docs/docker.md`:

````markdown
## Anonymous volumes, and the node_modules problem

```bash
docker run -v "D:/repo/web:/app" -v /app/node_modules IMAGE
```

The second `-v` has no host path. That is an **anonymous volume**, and its only job is
to mask a path that a bind mount would otherwise cover.

Without it, bind-mounting `web/` carries the host's `node_modules` into the container.
Two independent failures follow:

1. **Slow.** Every module read crosses the Windows/Linux filesystem boundary. A
   4-second Next.js compile becomes a minute or more.
2. **Wrong.** Packages with compiled binaries were built for Windows. Linux cannot
   execute them.

The anonymous volume shadows that path, so the container keeps the `node_modules`
built during `docker build`. Source stays live; packages stay correct.

## Running a different command

```bash
docker run --rm IMAGE sh -c "ls node_modules | wc -l && uname -s -m"
```

Anything after the image name replaces the image's `CMD`. Useful for inspecting an
image without starting its real workload.
````

- [ ] **Step 6: Commit**

```bash
git add Dockerfile.web docs/docker.md
git commit -m "feat(docker): frontend image with linux-built packages

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Compose, and the acceptance run

**Files:**
- Create: `docker-compose.yml`
- Modify: `docs/docker.md` (append two sections)

**Interfaces:**
- Consumes: `Dockerfile.engine` (Task 1–2) and `Dockerfile.web` (Task 3).
- Produces: `docker compose up` serving the frontend on `localhost:3000`, reaching the engine
  by the hostname `engine`.

- [ ] **Step 1: Write `docker-compose.yml`**

Create `docker-compose.yml` at the repository root:

```yaml
services:
  engine:
    build:
      context: .
      dockerfile: Dockerfile.engine
    ports:
      - "8000:8000"
    volumes:
      - .:/app
      - payoff-runtime:/app/Data/runtime

  web:
    build:
      context: .
      dockerfile: Dockerfile.web
    ports:
      - "3000:3000"
    volumes:
      - ./web:/app
      - /app/node_modules
    environment:
      BACKEND_ORIGIN: http://engine:8000
    depends_on:
      - engine

volumes:
  payoff-runtime:
```

`BACKEND_ORIGIN` is `http://engine:8000`, not `http://127.0.0.1:8000`. Inside a container,
`127.0.0.1` means *that container*, so the frontend would be calling itself. `engine` is the
service name, which Compose's embedded DNS resolves to the engine's container.

- [ ] **Step 2: Start from nothing**

Remove the volume from Task 2 so the first-run path is genuinely exercised:

```bash
docker volume rm payoff-runtime
docker compose up --build
```

Expected, interleaved and prefixed with service names:

1. `engine-1  | runtime tree absent - deriving 24 dates (about 50s, once)`
2. `engine-1  | Uvicorn running on http://0.0.0.0:8000`
3. `web-1     | ✓ Ready in ...`

Note Compose created the volume itself, from the `volumes:` block — the explicit
`docker volume create` is no longer needed.

- [ ] **Step 3: Verify service DNS from inside the web container**

In a second terminal:

```bash
docker compose exec web sh -c "wget -qO- http://engine:8000/docs | head -c 60"
```

Expected: the first bytes of an HTML page.

This is the network working: one container resolved another by service name, with no IP address
written anywhere.

- [ ] **Step 4: Run the acceptance path**

Open `http://localhost:3000`. Then:

1. Confirm the Chain renders for **2026-01-27**, expiry **10FEB26**.
2. Click **straddle**. Expected: two legs at 25,200 — CE at **344.05**, PE at **326.7**.
3. Click **Analyse 2 Legs →**.

Expected on the payoff page, exactly:

```
Max profit    Unlimited
Max loss        -670.75
Breakevens    24,529.25 · 25,870.75
Net premium      670.75 debit
```

**Any difference in these numbers is a defect, not a tolerance.** It would mean the
containerised engine is reading something the host engine did not. Stop and investigate rather
than proceeding.

- [ ] **Step 5: Verify both bind mounts are live**

Edit `src/payoff/api.py` — add a blank line and save. Expected: `engine-1` logs a reload.

Edit any file under `web/app/` — add a blank line and save. Expected: `web-1` recompiles and
the browser updates without a manual refresh.

Revert both edits:

```bash
git checkout -- src/payoff/api.py web/app
```

- [ ] **Step 6: Verify a restart is fast**

```bash
docker compose down
docker compose up
```

Expected: **no derivation message**, both services ready in about 10 seconds. `down` removes
containers and the network but **not** named volumes, so the runtime tree survives.

- [ ] **Step 7: Append to the cheat-sheet**

Append to `docs/docker.md`:

````markdown
## Compose

One file describing several containers and how they connect.

```bash
docker compose up              # start everything
docker compose up --build      # rebuild images first
docker compose up -d           # background
docker compose down            # stop and remove containers + network
docker compose down -v         # ...and named volumes. Forces a rebuild of the tree.
docker compose ps              # what is running
docker compose logs -f engine  # follow one service
docker compose exec web sh     # a shell inside a running container
```

`down` keeps named volumes. `down -v` destroys them — the only reason to use it here is
to force the runtime tree to be derived again.

## Service names are hostnames

Compose puts every service on one network and runs a DNS server on it. A service name
resolves to that service's container:

```yaml
environment:
  BACKEND_ORIGIN: http://engine:8000     # not 127.0.0.1
```

Inside a container `127.0.0.1` means *that container*. The frontend calling
`127.0.0.1:8000` would be calling itself. `engine` is the service name from
`docker-compose.yml`, and no IP address is ever written down.

`depends_on` orders startup only. It does not wait for readiness — the frontend proxies
per request, so the first page load absorbs any lag.

## Debugging a container

```bash
docker compose logs -f engine        # what did it say
docker compose exec engine sh        # get inside a running one
docker compose ps                    # is it even up
docker inspect payoff-project-engine-1 | head -40
```

If a container exits immediately, `logs` holds the reason. `exec` needs the container to
be running — for one that will not start, run its image with a shell instead:

```bash
docker run --rm -it payoff-engine:dev sh
```
````

- [ ] **Step 8: Commit**

```bash
git add docker-compose.yml docs/docker.md
git commit -m "feat(docker): compose the engine and frontend into one command

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

- [ ] **Step 9: Update the README**

Add to `README.md`, immediately after the `## Running the website` heading's existing content:

```markdown
### With Docker

One command, on a machine that has only Docker installed:

```bash
docker compose up
```

The engine derives the runtime tree on first start — about 50 seconds, once, into a named
volume. Later starts take about ten seconds. Source is bind-mounted, so edits reload without a
rebuild. See [`docs/docker.md`](./docs/docker.md).
```

Note while here: the Quick start section says *"expect: 101 passed"*. It is **179** as of
`56b5dbe`. Fix that number in the same commit.

```bash
git add README.md
git commit -m "docs: document the docker path, and correct the test count

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage.** Every file in the spec's *Files added* table has a task: `.dockerignore` and
`Dockerfile.engine` (1), `docker/engine-entry.sh` (2), `Dockerfile.web` (3),
`docker-compose.yml` (4), `docs/docker.md` (1–4). The spec's *Verification* list maps to Task 4
steps 2–6, and its *Teaching order* table maps to the cheat-sheet sections appended by each
task. The three non-goals — production images, containerised CI, splitting `requirements.txt` —
appear in no task, which is correct.

**Type consistency.** Image tags `payoff-engine:dev` and `payoff-web:dev` are used identically
in every task. The volume is `payoff-runtime` throughout. The manifest path
`/app/Data/runtime/manifest_v1/part-0.parquet` matches the volume mount point
`/app/Data/runtime`. `BACKEND_ORIGIN` matches the name the frontend already reads.

**Known risk, with its remedy in the plan.** Whether `bun run dev -- -H 0.0.0.0` forwards the
flag is unverified. Task 3 Step 4 tests for it explicitly and supplies the exact fallback
(`bunx next dev -H 0.0.0.0`) rather than leaving it to be discovered in Task 4.

**A second risk worth naming.** Compose mounts the whole repository at `/app` for the engine,
including `web/node_modules`. The engine never reads it, so this costs nothing at runtime, but
it does mean the engine container sees Windows binaries it will never execute. Left alone
deliberately — excluding it would need a third mount for no benefit.

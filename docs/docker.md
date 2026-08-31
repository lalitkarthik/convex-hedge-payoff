# Docker, as used in this project

Written while dockerising the dev environment. Each section was added when the command
was first needed. Measurements are from this machine on 2026-08-31.

## Images and containers

An **image** is a built filesystem plus a default command. A **container** is one running
instance of an image. Images are reusable; containers are disposable.

```bash
docker build -f Dockerfile.engine -t payoff-engine:dev .   # build an image
docker images                                              # list images
docker ps                                                  # running containers
docker ps -a                                               # all, including exited
docker run --rm IMAGE                                      # run, delete on exit
```

`-t` names the image. `-f` selects the Dockerfile. The trailing `.` is the **build context**.

Worth doing once to see the distinction: after a build, `docker images` lists the engine and
`docker ps -a` shows nothing. The recipe exists; nothing is cooking.

## The build context

The context is the directory handed to the builder, filtered by `.dockerignore`.

BuildKit — the default builder since Docker 23 — transfers it **lazily**: it sends only the
files a `COPY` instruction actually references. This Dockerfile copies just
`requirements*.txt`, so the observed transfer is **1.84 kB**, not the ~55 MB the directory
holds.

`.dockerignore` still matters, for two reasons that have nothing to do with that number:

- `docker compose` builds and any future `COPY . .` would send everything without it.
- `web/node_modules` (379 MB) and `web/.next` (204 MB) were built **on Windows**. The
  container is Linux. Those binaries cannot execute there, so they must never enter an image.

`Data/` is deliberately **not** ignored — the engine derives its runtime tree from it, and it
arrives by bind mount rather than by copy.

## Layers and the cache

Each Dockerfile instruction makes a layer. Docker reuses a layer when neither the instruction
nor its inputs changed, and invalidates **every layer after** the first change.

This is why dependency manifests are copied before source:

```dockerfile
COPY requirements.txt requirements-dev.txt ./   # changes rarely
RUN pip install ...                             # slow - stays cached
```

Measured here:

| | time |
|---|---|
| first build | **95.7 s** |
| rebuild after editing `src/payoff/api.py` | **3 s**, all layers `CACHED` |

A source edit cannot invalidate the pip layer, because the Dockerfile never copies source —
it arrives by bind mount at run time. Copying source before the install would turn every edit
into a 96-second reinstall.

```bash
docker history payoff-engine:dev    # the layers, and what each cost
```

## A note on image size

`docker images` reports **1.59 GB** for `payoff-engine:dev`. Most of that is jupyterlab,
matplotlib and scipy: `requirements.txt` bundles the notebook stack with the engine's own
dependencies, and the engine imports none of it.

Splitting that file would cut the image substantially. It is a change to the project's
dependency layout rather than to Docker, so it was recorded and left alone — dev parity with
the host environment is a defensible reason to keep one list.

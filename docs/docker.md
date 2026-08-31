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

## Entrypoints, and stopping cleanly

A container runs one command. When more than one thing must happen, put them in a script
and make the script that command.

```dockerfile
COPY docker/engine-entry.sh /entry.sh
RUN chmod +x /entry.sh          # git on Windows drops the executable bit
ENTRYPOINT ["/entry.sh"]
```

Two Windows-specific traps, both silent until they bite:

- **The executable bit.** Git on Windows does not carry it, so the copied script arrives
  non-executable and the container exits with `permission denied`. Hence the `chmod`.
- **Line endings.** A CRLF script fails with `bad interpreter: /bin/sh^M`. `.gitattributes`
  pins `*.sh text eol=lf` so a fresh clone cannot reintroduce it.

End the script with `exec`:

```sh
exec uvicorn payoff.api:app --host 0.0.0.0 --port 8000
```

`exec` replaces the shell with uvicorn, so the server becomes the container's main process.
You can see it worked: the log reads `Started server process [1]` - PID 1. Docker's stop
signal then reaches the server directly and **stopping takes 2 seconds**. Without `exec` the
signal goes to the shell, which ignores it, and Docker waits out a ten-second grace period
before killing the container.

## Ports

```bash
docker run -p 8000:8000 IMAGE     # host 8000 -> container 8000
```

Two separate numbers that usually match. Publishing is not enough on its own: the server
inside must also bind `0.0.0.0`. Bound to `127.0.0.1` it accepts connections only from inside
its own container - and the logs look perfectly healthy while nothing outside can reach it.

## Volumes

```bash
docker volume create payoff-runtime
docker volume ls
docker volume rm payoff-runtime                            # force the tree to rebuild
docker run -v payoff-runtime:/app/Data/runtime IMAGE       # named volume
docker run -v "D:/Convex Hedge/payoff-project:/app" IMAGE  # bind mount
```

A **bind mount** shows a host directory inside the container - used here for source, so edits
are live. A **named volume** is storage Docker owns; it survives `--rm` and rebuilds, and is
where derived data belongs.

A mount **masks** whatever is beneath it. Measured here:

| | |
|---|---|
| first start, empty volume | derives the tree, **~55 s** |
| restart | **4 s**, no derivation |

The empty volume hid the host's already-populated `Data/runtime`, which is why the first run
derived a tree the host already had. After that the volume holds it, and `--rm` does not touch
it.

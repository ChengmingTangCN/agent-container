# codex-container

Run Codex CLI inside a Docker container.

## Core idea

This setup treats Docker containers as disposable runtime environments.

By default, each time you run:

```bash
codex-container /path/to/project
```

the script creates a new container. Because the container is started with:

```bash
--rm
```

the container is automatically deleted after you exit it.

This is intentional.

If you want to keep the container after exit, run:

```bash
codex-container --persistent /path/to/project
```

In persistent mode, the container is reused on the next run for the same project path.

The persistent data is kept on the host:

```text
project files -> host project directory
Codex config  -> ~/.codex-container
Docker image  -> codex-dev:npm-local-<dockerfile-hash>-uid-<uid>-gid-<gid>
```

The container itself does not need to persist.

Starting a container is cheap and fast, because the image is reused after it is built once. So the normal workflow is:

```text
build image once
run temporary container
work on mounted project
exit container
container is deleted
run again when needed
```

## Naming rules

This setup is designed around two rules:

1. The Docker image is tied to the Dockerfile and the host user's UID/GID.
2. The Docker container name is tied to the project path.

The image is tied to UID/GID because the container runs as a normal user named `dev`, not as `root`.

The `dev` user inside the container uses the same UID/GID as the host user. This allows the container to modify mounted project files without creating root-owned files on the host.

The Dockerfile hash ensures that an updated Dockerfile automatically produces a
new image instead of silently reusing an outdated one. Example image name:

```text
codex-dev:npm-local-a1b2c3d4e5f6-uid-1000-gid-1000
```

The container name is tied to the project path so that one user can run Codex containers for multiple projects at the same time.

Example container name:

```text
codex-myproj-a1b2c3d4
```

The project is mounted inside the container under `/work/<project-name>`:

```text
~/dev/myproj -> /work/myproj
```

Summary:

```text
image     -> tied to Dockerfile and UID/GID
container -> tied to project path
workdir   -> /work/<project-name>
lifetime  -> temporary, deleted after exit
```

## Features

- Runs Codex CLI inside Docker
- Creates a temporary container for each run
- Automatically removes the container after exit
- Can keep and reuse a project container with `--persistent`
- Can force a clean image rebuild with `--rebuild`
- Reuses the Docker image after the first build
- Keeps project data on the host
- Keeps Codex config on the host
- Runs as normal user `dev`
- `dev` has passwordless sudo
- `dev` UID/GID matches the host user
- Installs npm global packages under `/home/dev/.npm-global`
- Installs Codex CLI as `dev`, so Codex can update its own package without sudo
- Project directory is mounted to `/work/<project-name>`
- Codex config is persisted in `~/.codex-container`
- Reuses host network with `--network host`
- Reuses host proxy environment variables
- Automatically builds a new image when the Dockerfile changes
- Refuses to mount `/`
- Allows multiple project containers to run at the same time

## Files

```text
codex-container/
├── Dockerfile
├── codex-container
└── README.md
```

## Setup

```bash
chmod +x codex-container
```

Install to user local bin:

```bash
mkdir -p ~/.local/bin
ln -s "$(pwd)/codex-container" ~/.local/bin/codex-container
```

Make sure `~/.local/bin` is in your `PATH`:

```bash
echo "$PATH" | tr ':' '\n' | grep -x "$HOME/.local/bin"
```

Then you can run it from anywhere:

```bash
codex-container ~/dev/myproj
```

## Usage

```bash
codex-container /path/to/project
codex-container --persistent /path/to/project
codex-container --rebuild /path/to/project
```

Example:

```bash
codex-container ~/dev/myproj
codex-container --persistent ~/dev/myproj
codex-container --rebuild ~/dev/myproj
```

Inside the container:

```bash
codex
```

Codex is installed under the `dev` user's npm prefix:

```text
/home/dev/.npm-global
```

This keeps Codex writable by `dev` instead of placing it in a root-owned global npm directory.

Exit the container:

```bash
exit
```

After exit, the container is deleted automatically. Your project files and Codex config remain on the host.

## Proxy

The script accepts either uppercase or lowercase proxy variables and passes both
forms into the build and the container:

```text
http_proxy
https_proxy
HTTP_PROXY
HTTPS_PROXY
no_proxy
NO_PROXY
```

Example:

```bash
export http_proxy=http://127.0.0.1:7890
export https_proxy=http://127.0.0.1:7890

codex-container ~/dev/myproj
```

Uppercase variables work as well:

```bash
export HTTP_PROXY=http://127.0.0.1:7890
export HTTPS_PROXY=http://127.0.0.1:7890
export NO_PROXY=localhost,127.0.0.1,::1
```

Proxy values are supplied as Docker's predefined build arguments. They are not
written to npm configuration files or printed by the Dockerfile. When no proxy
environment variables are set, the script leaves Docker's own build proxy
configuration untouched.

When `--rebuild` is used, the image is built without cache. If a container with
the same project name exists, it is removed first so persistent containers can
be recreated from the new image.

Because the container uses `--network host`, `127.0.0.1:7890` inside the container refers to the host proxy service on Linux.

## Codex config

Codex config is stored on the host at:

```text
~/.codex-container
```

It is mounted into the container as:

```text
/home/dev/.codex
```

If the directory does not exist, the script creates it automatically.

## Permission check

Inside the container:

```bash
whoami
id
sudo whoami
touch test-from-container
```

Expected:

```text
dev
uid=<host-uid>(dev) gid=<host-gid>(dev)
root
```

On the host:

```bash
ls -l test-from-container
```

The file should be owned by the host user, not root.

## Notes

Prefer mounting a specific project directory:

```bash
codex-container ~/dev/myproj
```

Avoid mounting broad directories such as:

```bash
codex-container ~
```

The script refuses to mount `/`.

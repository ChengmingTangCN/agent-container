# Agent authentication

HAPI authenticates the Runner to your Hub and starts agent processes. It does not
create provider accounts, obtain API keys, or complete browser/device login for
headless sessions. Its agent availability check tests the installed command, not
provider authentication. A session can start and still fail on its first prompt.

Open the shell printed by the launcher: `docker exec -it <container> bash`.
Configure only the agents you use; missing Codex credentials do not block Pi.

## Codex

```bash
codex login --device-auth  # Follow the URL/code; enable device login if required.
# If unavailable: codex login
codex login status
```

For an OpenAI API key supplied through an env file:

```bash
printenv OPENAI_API_KEY | codex login --with-api-key
```

Use file credential storage for persistence in this container; set
`cli_auth_credentials_store = "file"` in `~/.codex/config.toml` if necessary.
`~/.codex/auth.json` is stored in the project's mounted `codex/` directory.
The host's keyring/login is not automatically available inside Docker.

Missing `auth.json` does not always mean missing authentication: a custom provider
can use `env_key` from the container environment, or require no key for a local
model. Configure it in `~/.codex/config.toml`; referenced files must exist inside
the container. `codex login status` reports local login state, not a live check of
every provider, token, quota or model. See [Codex authentication](https://developers.openai.com/codex/auth/).

### Project state and trusted seed

Each project has separate Codex, Pi, and OpenCode homes under
`~/.agent-container/projects/<path-hash>/` on the host. Native sessions, history,
and runtime state therefore do not appear in another project's container. The
launcher never mounts or automatically imports the host user's agent homes.

For a new project only, the launcher copies these optional trusted seed files:

```text
~/.agent-container/seed/
├── AGENTS.md          -> independent Codex, Pi, and OpenCode copies
├── codex/
│   ├── auth.json      -> codex/auth.json
│   └── config.toml    -> codex/config.toml
├── pi/
│   ├── auth.json      -> pi/agent/auth.json
│   ├── settings.json  -> pi/agent/settings.json
│   └── models.json    -> pi/agent/models.json
└── opencode/
    ├── auth.json      -> opencode/data/auth.json
    └── opencode.json  -> opencode/config/opencode.json
```

Populate only the files needed for future projects:

```bash
install -d -m 700 ~/.agent-container/seed/{codex,pi,opencode}
install -m 600 ~/.codex/auth.json ~/.agent-container/seed/codex/auth.json
install -m 600 ~/.codex/config.toml ~/.agent-container/seed/codex/config.toml
install -m 600 ~/.pi/agent/auth.json ~/.agent-container/seed/pi/auth.json
install -m 600 ~/.pi/agent/settings.json ~/.agent-container/seed/pi/settings.json
install -m 600 ~/.pi/agent/models.json ~/.agent-container/seed/pi/models.json
install -m 600 ~/.local/share/opencode/auth.json ~/.agent-container/seed/opencode/auth.json
install -m 600 ~/.config/opencode/opencode.json ~/.agent-container/seed/opencode/opencode.json
install -m 600 /path/to/AGENTS.md ~/.agent-container/seed/AGENTS.md
```

If login was completed inside a project container, copy from that project's
`codex/auth.json`, `pi/agent/auth.json`, or `opencode/data/auth.json` under the
`State:` directory printed by the launcher instead. `AGENT_CONTAINER_DATA_DIR` replaces
`~/.agent-container` in these paths when set.

Seeding copies files; it does not live-share them. Existing project state is
never overwritten, so add or replace its files manually while its Runner is
stopped. The three instruction files may diverge after initialization. Older
projects keep any instruction links created by an earlier launcher. Do not
bind-mount one host `auth.json` file into every container: agents can refresh or
remove file-backed credentials, and concurrent containers should not write the
same credential file.

Choose the Codex model and reasoning effort when creating a HAPI session or from
that session's controls. HAPI applies those values to the individual Codex
thread; it does not rewrite the seeded `config.toml`. This launcher does not add
or synchronize named Codex profiles.

## Pi and OpenCode

For Pi, run `pi`, use `/login` to select a provider and enter its API key or complete
OAuth, then `/model` to choose a model. Save the default with Ctrl+S in the model
selector, or set `defaultProvider` and `defaultModel` in `~/.pi/agent/settings.json`.
Alternatively pass provider variables such as `ANTHROPIC_API_KEY` or
`OPENAI_API_KEY` through an env file. Pi's `~/.pi/agent/` stores credentials,
settings and native sessions in the project's mounted `pi/` directory. Custom
providers and models belong in `~/.pi/agent/models.json`; generated
`models-store.json` catalog data is cache and is not seeded.

`pi auth check --provider anthropic --no-refresh` checks locally configured
credentials without printing them or refreshing OAuth. This still does not prove
that a key works at the provider. HAPI runs Pi in RPC mode; complete interactive
login in the native `pi` terminal, then create a new HAPI session. See
[Pi providers](https://github.com/earendil-works/pi-mono/blob/main/packages/coding-agent/docs/providers.md).

For OpenCode, run `opencode auth login`, then choose the provider/model in
`opencode`. Credentials are stored in `~/.local/share/opencode/auth.json`; custom
provider and model definitions belong in `~/.config/opencode/opencode.json`.
Its config, data, and state directories are mounted separately. See
[OpenCode providers](https://opencode.ai/docs/providers/).

Codex, Pi and OpenCode are installed in the image. More agents need their native
CLI, provider setup and persistent state mount; installing a CLI alone does not
add persistence. Follow [the pinned HAPI support matrix](https://github.com/tiann/hapi/blob/0239edf38e2da653d662f31039e24ccea04c7837/docs/guide/agents.md)
for permissions, remote input and resume limitations.

## Environment files

Create a private file outside the project and edit only the values you need:

```bash
install -d -m 700 ~/.config/agent-container
(umask 077; touch ~/.config/agent-container/myproj.env)
chmod 600 ~/.config/agent-container/myproj.env
${EDITOR:-vi} ~/.config/agent-container/myproj.env
agent-container --hapi --env-file ~/.config/agent-container/myproj.env ~/dev/myproj
```

Docker env-file syntax is `NAME=value`, without `export`, quotes, or shell
expansion. For example, use `ANTHROPIC_API_KEY=<your-key>` for Pi; unattended first
setup also needs `HAPI_API_URL=https://your-hub` and `CLI_API_TOKEN=<hub-token>`.
An interactive Hub login can instead keep its token in project state.

Keys are passed to the container and Runner's child agents, never to the image
build. Host provider environment variables are not copied automatically. Exporting
a key in an extra shell only affects children of that shell, not the running
Runner. Recreate the container to update its environment, repeating `--env-file`;
use the same file on each recreation. Do not override `HOME`, `HAPI_HOME`,
`CODEX_HOME`, `PI_CODING_AGENT_DIR` or XDG paths: the documented mounts use defaults.

Env values are visible to container processes and Docker administrators, and fall
under the same privacy contract as mounted data. Do not put keys in prompts.
After setup, send a small prompt with the intended provider/model to test actual
access. If it fails, check expired/revoked credentials, balance, model permission,
network/proxy and referenced config files; log in again and start a new session.

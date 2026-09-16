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

## Pi and OpenCode

For Pi, run `pi`, use `/login` to select a provider and enter its API key or complete
OAuth, then `/model` to choose a model. Save the default with Ctrl+S in the model
selector, or set `defaultProvider` and `defaultModel` in `~/.pi/agent/settings.json`.
Alternatively pass provider variables such as `ANTHROPIC_API_KEY` or
`OPENAI_API_KEY` through an env file. Pi's `~/.pi/agent/` stores credentials,
settings and native sessions in the project's mounted `pi/` directory.

`pi auth check --provider anthropic --no-refresh` checks locally configured
credentials without printing them or refreshing OAuth. This still does not prove
that a key works at the provider. HAPI runs Pi in RPC mode; complete interactive
login in the native `pi` terminal, then create a new HAPI session. See
[Pi providers](https://github.com/earendil-works/pi-mono/blob/main/packages/coding-agent/docs/providers.md).

For OpenCode, run `opencode auth login`, then choose the provider/model in
`opencode`. Its config, data (including credentials), and state directories are
mounted separately. See [OpenCode providers](https://opencode.ai/docs/providers/).

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

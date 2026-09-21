"""One-shot setup and readiness checks for the pinned, unmodified HAPI Hub."""

import getpass
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request


class SetupError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward credentials to a redirected host.
        return None


def read_settings(path):
    try:
        settings = json.loads(path.read_text()) if path.exists() else {}
        if not isinstance(settings, dict):
            raise ValueError
        if any(key in settings and not isinstance(settings[key], str)
               for key in ("apiUrl", "cliApiToken", "machineId")):
            raise ValueError
        return settings
    except (OSError, ValueError):
        raise SetupError("Cannot read HAPI settings.json; fix its JSON and permissions. No files were replaced.") from None


def hub_url(value):
    try:
        url = urllib.parse.urlsplit(value)
        local = url.hostname in ("localhost", "127.0.0.1", "::1")
        if (not url.hostname or url.username or url.password or url.query or url.fragment
                or url.path not in ("", "/") or (not url.port and url.netloc.endswith(":"))):
            raise ValueError
        if url.scheme != "https" and not (url.scheme == "http" and local):
            raise ValueError
    except ValueError:
        raise SetupError("Use an HTTPS Hub origin (http://localhost:3006 is allowed for local testing); no credentials or path in the URL.") from None
    return value.rstrip("/")


def request(url, path, *, token=None, body=None, timeout=8):
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "curl/8.0",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url + path, headers=headers,
                                 data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.build_opener(NoRedirect).open(req, timeout=timeout) as response:
        return json.load(response)


def authenticate(url, token, timeout=8):
    response = request(url, "/api/auth", body={"accessToken": token}, timeout=timeout)
    if not isinstance(response, dict) or not isinstance(response.get("token"), str) or not response["token"]:
        raise SetupError("Hub returned an unexpected login response; check the URL and Hub version.")
    return response["token"]


def prompt(label, secret=False):
    if not sys.stdin.isatty():
        raise SetupError("First --hapi setup needs a terminal, or --env-file with HAPI_API_URL and CLI_API_TOKEN. Rerun interactively; hapi auth login alone does not verify the Hub.")
    value = (getpass.getpass(label) if secret else input(label)).strip()
    if not value:
        raise SetupError("Setup cancelled: an empty value was supplied.")
    return value


def setup(path):
    settings = read_settings(path)
    url = hub_url(os.environ.get("HAPI_API_URL") or settings.get("apiUrl") or prompt("Hub URL (https://...): "))
    env_token = os.environ.get("CLI_API_TOKEN")
    # A token saved for one Hub must not be silently sent to another Hub.
    old_url = settings.get("apiUrl")
    saved_token = settings.get("cliApiToken") if not old_url or hub_url(old_url) == url else None
    token = env_token or saved_token
    if not token:
        print("Enter the Hub access token (VPS: /etc/agent-hapi/hapi-access-token). Input is hidden.", flush=True)
        token = prompt("Hub token: ", secret=True)
    try:
        authenticate(url, token)
    except urllib.error.HTTPError as error:
        if error.code != 401 or env_token or not sys.stdin.isatty():
            raise
        print("Hub rejected the saved/entered token. Enter a replacement (Ctrl-C cancels).", flush=True)
        token = prompt("Hub token: ", secret=True)
        authenticate(url, token)
    updated = {**settings, "apiUrl": url}
    if not env_token:
        updated["cliApiToken"] = token
    elif old_url and hub_url(old_url) != url:
        updated.pop("cliApiToken", None)
    # Save only after successful authentication; preserve machine identity.
    if updated != settings:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as out:
                temporary = Path(out.name)
                json.dump(updated, out, indent=2)
                out.write("\n")
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    print("Hub authentication verified. URL saved; environment tokens stay in the container environment.")


def ready(path, wait_seconds=45):
    settings = read_settings(path)
    url = hub_url(os.environ.get("HAPI_API_URL") or settings.get("apiUrl") or "http://localhost:3006")
    token = os.environ.get("CLI_API_TOKEN") or settings.get("cliApiToken")
    if not token:
        raise SetupError("Hub token is missing. Run hapi auth login in the container, or recreate it to repeat setup.")
    deadline = time.monotonic() + wait_seconds
    jwt = None
    last_error = "Runner has not registered its machine identity."
    while time.monotonic() < deadline:
        try:
            if jwt is None:
                jwt = authenticate(url, token, timeout=min(8, max(0.1, deadline - time.monotonic())))
            machine_id = read_settings(path).get("machineId")
            if machine_id:
                response = request(url, "/api/machines/" + urllib.parse.quote(machine_id, safe="") + "/agent-availability",
                                   token=jwt, timeout=min(8, max(0.1, deadline - time.monotonic())))
                if not isinstance(response, dict) or not isinstance(response.get("agents"), list) or not response["agents"]:
                    raise SetupError("Unexpected Runner RPC response; check Hub/Runner versions.")
                print("Runner ready: Hub login and a round-trip RPC succeeded.")
                return
        except urllib.error.HTTPError as error:
            if error.code in (401, 403, 409, 429) or 300 <= error.code < 400:
                raise
            last_error = f"Hub HTTP {error.code}; Runner is offline or RPC is not ready."
        except (urllib.error.URLError, TimeoutError, OSError):
            last_error = "Cannot reach Hub/Runner; check network, TLS and HTTP(S)_PROXY/NO_PROXY."
        time.sleep(min(2, max(0, deadline - time.monotonic())))
    raise SetupError("Runner readiness timed out. " + last_error)


def main():
    path = Path(os.environ.get("HAPI_HOME", "~/.hapi")).expanduser() / "settings.json"
    try:
        if sys.argv[1:] == ["setup"]:
            setup(path)
        elif sys.argv[1:] == ["ready"]:
            ready(path)
        else:
            raise SetupError("Expected setup or ready.")
    except urllib.error.HTTPError as error:
        detail = {401: "Hub rejected the token.", 403: "Hub denied access; check the token and access policy.",
                  409: "Hub and Runner versions are incompatible.", 429: "Hub rate limit reached; wait before retrying."}.get(error.code, "Check the Hub URL, version and reverse proxy; redirects are not followed.")
        print(f"HAPI: HTTP {error.code}. {detail}", file=sys.stderr)
        return 1
    except (SetupError, OSError, ValueError, EOFError, KeyboardInterrupt) as error:
        message = str(error) if isinstance(error, SetupError) else "Setup/check failed or cancelled; check configuration, network, TLS and HTTP(S)_PROXY/NO_PROXY."
        # Do not echo server bodies, credentials, or network exception URLs.
        print("HAPI: " + message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Headless Drive mount for a live colab session.

Usage: python ops/drive_mount.py <session-name>   (run with the colab-cli venv python)

Intercepts the kernel's dfs_ephemeral Drive-auth request, obtains a consent URL,
prints it (and writes it to /tmp/drive_auth_url_<name>.txt), polls until the human
approves it in a browser, then completes credential propagation. The command's own
stdout is unbuffered; run with `python -u` and redirect to a log to watch progress.

Requires: google-colab-cli installed (imports colab_cli), a session already created
with `colab new -s <name>`, and the user's browser for consent (first mount per VM).
Consent must be re-done for every new runtime endpoint.

Run with the CLI's venv python, e.g.:
  ~/.local/share/uv/tools/google-colab-cli/bin/python -u ops/drive_mount.py mzr-finetune
"""
import json, time, os, sys
from colab_cli.common import state
from colab_cli.runtime import ColabRuntime
from colab_cli.auth import get_credentials
from colab_cli.utils import get_status_code

NAME = sys.argv[1] if len(sys.argv) > 1 else "mzr-finetune"
URL_OUT = f"/tmp/drive_auth_url_{NAME}.txt"
s = state.get_session(NAME)
runtime = ColabRuntime(s.url, s.token, session_name=s.name, history=state.history)
creds = get_credentials(state.client_oauth_config, provider=state.auth_provider)
PROP_URL = f"{state.client.colab_domain}/tun/m/credentials-propagation/{s.endpoint}"
PARAMS = {"authuser": "0", "authtype": "dfs_ephemeral",
          "version": "2", "propagate": "true", "record": "false"}

def get_token():
    r = creds.request("GET", PROP_URL, params={**PARAMS, "dryrun": "true"})
    t = r.text.split("\n", 1)[-1]
    print("GET", get_status_code(r), flush=True)
    try:
        return json.loads(t).get("token")
    except Exception:
        return None

def post(token, dryrun):
    r = creds.request("POST", PROP_URL, params={**PARAMS, "dryrun": dryrun},
                      headers={"x-goog-colab-token": token},
                      files={"file_id": (None, "empty.ipynb")})
    t = r.text.split("\n", 1)[-1]
    print(f"POST[{dryrun}]", get_status_code(r), t[:220], flush=True)
    try:
        return json.loads(t)
    except Exception:
        return {}

def drivefs_hook(deserialize_msg, wsclient):
    if deserialize_msg.get("content", {}).get("request", {}).get("authType") != "dfs_ephemeral":
        return False
    msg_id = deserialize_msg.get("metadata", {}).get("colab_msg_id")
    print("INTERCEPTED", msg_id, flush=True)
    token = get_token()
    data = post(token, "false") if token else {}
    if not data.get("success"):
        t2 = post(token, "true")  # dryrun=true yields the consent URL pre-consent
        uri = t2.get("unauthorized_redirect_uri") or data.get("unauthorized_redirect_uri")
        print("AUTH_URL:", uri, flush=True)
        if uri:
            with open(URL_OUT, "w") as f:
                f.write(uri)
        deadline = time.time() + 3300
        while time.time() < deadline:
            time.sleep(10)
            token = get_token()
            data = post(token, "false") if token else {}
            if data.get("success"):
                print("CONSENT_DETECTED", flush=True)
                break
        else:
            print("GAVE_UP_WAITING", flush=True)
            return False
    reply = wsclient.session.msg("input_reply",
        {"value": {"type": "colab_reply", "colab_msg_id": msg_id}})
    if "header" in deserialize_msg:
        reply["parent_header"] = deserialize_msg["header"]
    wsclient.stdin_channel.send(reply)
    print("CREDENTIALS_PROPAGATED", flush=True)
    return True

runtime.colab_request_hook = drivefs_hook
try:
    outputs = runtime.execute_code(
        "from google.colab import drive\ndrive.mount('/content/drive')",
        allow_stdin=True, timeout=3600)
    for out in outputs:
        print("OUT:", json.dumps(out)[:800], flush=True)
except Exception as e:
    print("EXEC_ERROR", type(e).__name__, str(e)[:500], flush=True)
finally:
    runtime.stop()
    print("RUNTIME_STOPPED", flush=True)

# Music: a scriptable app

This adapter reads playback state and sends fixed play or pause commands to `com.apple.Music`. It shows the Apple Events variant without needing Things or direct database access. Read [the adapter](../../src/clawbridge/examples/music.py) alongside its [build configuration](../../packaging/macos/music.toml).

| Request | Parameters | Effect |
| --- | --- | --- |
| `GET /music/state` | None | Returns `not_running` or the current player state. The running check does not use System Events. |
| `POST /music/play` | `{}` | Asks Music to play. This can launch Music and start audio. |
| `POST /music/pause` | `{}` | Asks Music to pause. This can launch Music if it is closed. |

Every request needs the private bearer token. Play and pause are mutations, so they use the shared operation journal and uncertainty rules. An accepted command does not promise that a track was available or that audio is audible. If a mutation's outcome is unknown, inspect Music and the operation record before making another request.

## Permissions

The MCP profile `music` exposes `music_state`, `music_play` and `music_pause`, plus `bridge_status`, `get_operation` and `list_operations`. Use the client configuration in the standalone `REFERENCE.md`, selecting `--profile music` and the helper's absolute socket and token paths. The default runtime is `~/Library/Application Support/ClawBridgeMusic/`; expand `~` in client JSON. The MCP process does not start the helper or gain its permissions.

For example, replace the paths with those on your Mac:

```json
{
  "mcpServers": {
    "music": {
      "command": "/Users/you/clawbridge/.venv/bin/clawbridge-mcp",
      "args": ["--profile", "music", "--socket", "/Users/you/Library/Application Support/ClawBridgeMusic/bridge.sock", "--token-file", "/Users/you/Library/Application Support/ClawBridgeMusic/bridge.token"]
    }
  }
}
```

The app needs Automation consent to control Music. It does not read Music's database or request Full Disk Access, Accessibility, Screen Recording or System Events. The usage description names the three supported operations.

For the experimental sandbox build, `scripting_targets` selects only `com.apple.Music.playback`. The Music dictionary supplied with the development host declares that group for play, pause and player state. Inspect your target OS's `/System/Applications/Music.app/Contents/Resources/com.apple.Music.sdef` before adapting this example. Apple recommends scripting access groups when a target provides them, rather than a whole-app temporary exception. [Apple's entitlement reference](https://developer.apple.com/library/archive/documentation/Miscellaneous/Reference/EntitlementKeyReference/Chapters/AppSandboxTemporaryExceptionEntitlements.html).

This group is narrower than all of Music, but includes more than these three operations. The adapter's fixed action set provides the remaining restriction. The normal unsandboxed build does not gain sandbox confinement just because its configuration names a group. Automation consent remains separate in both profiles.

## Build and try it

From the repository root, with the locked environment installed:

```sh
scripts/build_bridge_app.sh --config packaging/macos/music.toml --output build/music-candidate
scripts/sign_bridge_app.sh --config packaging/macos/music.toml \
  --app 'build/music-candidate/ClawBridge Music.app' \
  --profile local --identity 'Your Existing Local Identity'
'build/music-candidate/ClawBridge Music.app/Contents/MacOS/ClawBridge Music' --health
```

The local `--health` command sends no Apple Events. Use an existing signing identity for the consent workflow. Ad-hoc signing is suitable for build checks, not a claim of persistent consent identity. See [the signing guide](../bridge-build.md) for profile details.

To exercise actual Music access, start the signed executable in the foreground, then run the following read request from another terminal. Be present to review any permission prompt. A prompt attributed to a different process is a failed attribution check to investigate, not a reason to grant several processes access.

```sh
'build/music-candidate/ClawBridge Music.app/Contents/MacOS/ClawBridge Music'
```

```sh
.venv/bin/python - <<'PY'
import http.client
import socket
from pathlib import Path

runtime = Path.home() / "Library/Application Support/ClawBridgeMusic"
connection = http.client.HTTPConnection("localhost", timeout=35)
connection.sock = socket.socket(socket.AF_UNIX)
connection.sock.settimeout(35)
connection.sock.connect(str(runtime / "bridge.sock"))
try:
    token = (runtime / "bridge.token").read_text().strip()
    connection.request("GET", "/music/state", headers={"Authorization": f"Bearer {token}"})
    response = connection.getresponse()
    print(response.status, response.read().decode())
finally:
    connection.close()
PY
```

The client reads the token inside its process. It does not put the token in shell arguments. Change the request deliberately to `POST /music/play` or `/music/pause` with body `{}` only when you want to change playback. Stop the foreground service with Control-C. Installation as a LaunchAgent is a separate step in the shared guide.

Add `--sandbox-experimental` at build time to select the restricted profile. For a sandboxed foreground run, pass `--socket` and `--token-file` inside `~/Library/Containers/org.example.ClawBridgeMusic/Data/`; the installer selects these paths automatically. Update the client's runtime path to match. Real Music playback and its sandbox scripting group still need acceptance testing on the exact candidate; mocked tests cannot establish either.

## Adapt it

Replace the fixed scripts, schemas and routes with the app's supported dictionary commands. Send data through a safe separate channel if commands need parameters; never interpolate arbitrary caller code. Update the bundle identity, usage description and verified scripting access groups. If the target offers no groups, declare only that target in `apple_event_targets` and document that coarser boundary.

The tests intercept `/usr/bin/osascript`; they never control Music. They verify script selection, parameter rejection, denied Automation, unexpected replies and mutation classification. The shared worker keeps other post-dispatch failures uncertain instead of assuming no action happened.

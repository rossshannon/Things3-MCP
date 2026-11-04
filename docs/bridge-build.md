# Build and install a macOS bridge

The bridge is a native PyInstaller **onedir** app. Building, signing and installing are separate commands. A build does not launch an app, install a service, create a certificate or request a privacy grant.

Use the committed `uv.lock` and `.python-version`. The build command creates a fresh environment, selects the locked `build` dependency group with `uv sync --locked --no-default-groups --group build`, and builds for the interpreter's native architecture. Run on macOS with uv, the pinned Python, and Apple's command-line tools available. The shell entry points work from any directory and use the project environment or `uv run --locked`; they do not use Apple's system Python.

```sh
uv sync --locked --group build
scripts/build_bridge_app.sh --output build/local-candidate
```

The default configuration is `packaging/macos/bridge.toml`. In this repository it preserves the existing Things app name, bundle identifier, local signing identity name and runtime paths. The standalone export maps the synthetic example configuration to the same default filename. The package version in `pyproject.toml` supplies both bundle version fields. The usage description explains reads and writes. Configurations declare a fixed entry module, collected packages, optional icon, app identity, relative runtime paths and permission targets. Plists are generated with Python's plist library; HOME paths containing spaces, ampersands or XML characters are not interpolated into XML text.

The [small examples](examples/README.md) also supply `music.toml` and `catalogue.toml`. For sandboxed scripting, `scripting_targets` maps a target bundle identifier to its declared access groups; use `apple_event_targets` only when whole-target access is needed. Both require an accurate Apple Events usage description. The Music example declares its playback group and no whole-target exception. These build declarations do not grant Automation consent.

Use a fresh output directory for each build. The command refuses to replace an app already in that directory. Build working files and its dedicated environment remain below that output directory for inspection. It does not remove other builds.

The synthetic adapter uses its own identity and requires no Things installation:

```sh
scripts/build_bridge_app.sh --config packaging/macos/example.toml --output build/example-candidate
scripts/sign_bridge_app.sh --config packaging/macos/example.toml \
  --app 'build/example-candidate/ClawBridge Example.app' --profile ad-hoc-test
```

`Contents/Resources/build-manifest.json` records the build identifier, package version, source revision and dirty status, source-input hashes, lock and configuration hashes, Python and build-tool versions, host operating system, SDK, architecture and intended entitlements. The build rejects source-input changes during compilation. A source export without Git has a null revision; retain its export provenance manifest alongside the build evidence. The runtime reads the sealed bundle manifest and returns its identity through authenticated `/status`.

Unsigned file hashes are written beside the app. Signing writes a separate `*.signed-artifact.json` containing final file hashes, symlink destinations and signature details. Keep these with the source revision and validation results. Signing timestamps and the host toolchain mean this is a repeatable build procedure, not a promise of byte-identical signed output. Do not edit the app after final signing.

## Signing profiles

**Local signing** uses an existing local code-signing identity after the frozen bundle is built. It does not turn on hardened runtime. For the Things configuration, the default identity name is `Things3 MCP Local`; another configuration must supply its own existing identity. Keys stay in Keychain, never the source tree or app bundle.

```sh
scripts/sign_bridge_app.sh --app 'build/local-candidate/Things3 MCP Bridge.app' \
  --profile local --identity 'Things3 MCP Local'
```

The command fails if the identity is missing. Certificate creation and trust settings are separate user decisions; the script never changes them. A stable identity can help preserve consent, but signature verification alone does not establish TCC attribution or permission retention.

**Developer ID signing** requires an existing Developer ID Application identity, signs with hardened runtime and a secure timestamp, and is the distribution profile:

```sh
scripts/sign_bridge_app.sh --app 'build/local-candidate/Things3 MCP Bridge.app' \
  --profile developer-id --identity 'Developer ID Application: Your Name (TEAMID)'
```

Both profiles sign nested Mach-O code and nested bundle containers inside out. They use `--deep` only for verification, never as the signing strategy. No profile disables library validation, allows unsigned executable memory, or grants JIT access. If a dependency needs an exception, investigate and validate that dependency before changing the profile. Local self-signed identities must not be passed to PyInstaller's hardened signing option; see [PyInstaller's macOS signing notes](https://pyinstaller.org/en/v6.20.0/feature-notes.html).

**Ad-hoc test signing** is explicit through `--profile ad-hoc-test`. The older `--adhoc` argument remains an alias. This profile is for synthetic tests and does not provide a persistent TCC identity. Do not treat it as the local consent or distribution workflow.

Developer ID signing is only one distribution gate. Submit the distributable with `notarytool`, inspect its log, staple the accepted ticket to the app, rebuild the archive and validate Gatekeeper on the final artefact. These scripts do not notarise, publish or claim those checks passed. Follow [Apple's notarisation workflow](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow) and [inside-out signing guidance](https://developer.apple.com/library/archive/technotes/tn2206/).

## Installation and recovery

Installation is an explicit change to the current user's app and LaunchAgent. Inspect the signed candidate before running it:

```sh
codesign --verify --deep --strict 'build/local-candidate/Things3 MCP Bridge.app'
scripts/install_bridge_launchagent.sh --app 'build/local-candidate/Things3 MCP Bridge.app'
```

The installer verifies the candidate's signature integrity and bundle identifier before touching the old service. It copies into a private staging directory on the destination volume and verifies the staged copy again. It retains the previous app and plist, stops the job with `launchctl bootout`, replaces the app and plist, then bootstraps the new job.

Readiness requires authenticated `/status` with the expected build identifier, version and bundle identifier. Its process identifier must match the LaunchAgent's process, and both status and process inspection must identify the installed executable. Public `/health` is not installation proof. A failed startup or mismatched response restores the previous app and plist and restarts a previously loaded job. A failed recovery is reported separately with the recovery directory; it is never reported as a successful install. Readiness of a legacy restored app is not established by merely loading its old job.

Successful installs retain their prior files in a private hidden directory under `~/Applications`, whose path is printed. Recovery backups can contain old code and should be removed deliberately after acceptance; the installer does not delete them automatically. Token, cache and operation-journal contents are preserved. Existing permissions on shared `~/Applications` and `~/Library/LaunchAgents` directories are preserved; app state is private, plists are mode `0600`, and the LaunchAgent uses umask `0077`.

Launchd stdout and stderr go to `/dev/null`, so arbitrary process output cannot create unbounded log files or persist request payloads. Use authenticated status and operation records for diagnostics, plus a foreground run with synthetic input when diagnosing startup. Existing log files are not removed. This choice deliberately provides no historical stdout/stderr log.

The LaunchAgent uses Apple's `AssociatedBundleIdentifiers` field. There are no parent-runtime heuristics or private responsibility APIs. It runs during the user's logged-in session; it does not promise operation before login or after logout. User-disabled background items and privacy consent remain user choices. The installer never opens Privacy settings, requests grants or removes existing TCC entries. [Apple's LaunchAgent documentation](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html) describes this lifecycle.

Uninstall uses the matching GUI-domain `bootout`, then removes only this app and its plist:

```sh
scripts/uninstall_bridge_launchagent.sh
```

It preserves private state and installation backups. Every lifecycle command accepts `--config`; installation and removal also accept `--home` for isolated fixtures. Tests stub `codesign` and `launchctl` and never operate on a real installation.

## Experimental App Sandbox profile

The default build remains unsandboxed. An explicit experimental build enables signed App Sandbox entitlements:

```sh
scripts/build_bridge_app.sh --config packaging/macos/example.toml \
  --sandbox-experimental --output build/example-sandbox
scripts/sign_bridge_app.sh --config packaging/macos/example.toml \
  --app 'build/example-sandbox/ClawBridge Example.app' --profile ad-hoc-test
```

For Things, the experimental profile adds only read-only access to the specific Things group-container directory and Apple Events authority for `com.culturedcode.ThingsMac`. It does not name System Events, another app group, the home directory, networking, Accessibility or a writable Things database. The app's own sandbox container supplies writable state. Normal sandbox resources remain available: this is not a claim that the process can access only one directory. Automation consent also permits the supported Things scripting operations; it is not an operating-system create-only permission.

A bounded native experiment established private-file read-only enforcement, denied sibling and symlink access in parent and child processes, and a Unix socket reachable from an external client inside the app's own container without networking entitlements. The same socket failed in an external permitted state directory. A separate ad-hoc signed synthetic PyInstaller build then passed authentication, same-executable worker, read/write, operation-journal and external Unix-client checks inside that container, without network or Apple Events entitlements. This establishes the tested synthetic frozen-Python path. Actual Things data access, Full Disk Access interaction, clean-client TCC behaviour and operation while the screen is locked remain separate acceptance gates.

The experimental installer selects these paths from the sealed build manifest:

```text
~/Library/Containers/<bundle-id>/Data/bridge.sock
~/Library/Containers/<bundle-id>/Data/bridge.token
```

The Things cache moves to `Data/cache/latest.json` through its existing cache environment variable. Operation records must stay beside the configured bridge state. The short socket layout is deliberate: macOS permits at most 103 pathname bytes, and the installer rejects longer paths before stopping a service. It does not add a network entitlement to work around that limit.

This is an explicit path migration. An external Things client must select the new socket and token with `THINGS3_MCP_BRIDGE_SOCKET` and `THINGS3_MCP_BRIDGE_TOKEN_FILE`. Old tokens, caches and journals remain in their old location; they are not copied or deleted automatically. Do not change a live installation to this profile until the exact frozen artifact, same-executable worker, socket, container home resolution, SQLite/WAL reads and intended client have passed isolated acceptance. Real Things reads and writes, consent retention, restart and locked-session checks require a disposable library and separate authorisation. FDA, if required for the real target, remains distinct from App Sandbox confinement; see [Apple's explanation](https://developer.apple.com/forums/thread/807142).

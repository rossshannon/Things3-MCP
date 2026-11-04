# Choose a small reference

Each example is a complete adapter around the same private socket, authentication, worker and recovery code. Start with the closest example and replace its fixed actions with your app's supported operations.

| Example | What it demonstrates | Privacy permission | Optional App Sandbox scope |
| --- | --- | --- | --- |
| [Counter and echo](../../src/clawbridge/demo.py) | Reading and changing the bridge's own synthetic state | None | Its own container only |
| [Music playback](music.md) | AppleScript commands for one scriptable app | Automation for Music | Music's declared playback scripting access group |
| [SQLite catalogue](catalogue.md) | Fixed, parameterised reads from an existing data file | None for the supplied synthetic fixture | Read-only access to the catalogue directory |

The [Things3-MCP integration](https://github.com/rossshannon/Things3-MCP) combines scripting and database access in a larger adapter. A protected database may need a separate Full Disk Access grant; the catalogue example explains how to adapt the file-access pattern without pretending that its fixture tests prove access to another app's data.

These are alternatives with separate app identities and configurations. They are not permissions to enable together. Choose the least privileged interface that provides the required operations. Prefer a supported API or export when the app has one. Computer Use remains useful when an app exposes only a graphical interface; a fixed bridge is useful when the required operations already have a structured API or scripting dictionary.

The examples accept fixed actions and ordinary data parameters. None accepts a script body, executable, app identifier, SQL statement or database path from a remote caller. Paths in code constrain the service's intended behaviour; signed App Sandbox entitlements provide a separate operating-system restriction. Full Disk Access does not bypass those sandbox checks. [Apple's explanation](https://developer.apple.com/forums/thread/807142).

Use [the shared build guide](../bridge-build.md) for signing and installation, and [the adaptation guide](../adapting-clawbridge.md) for remote-client boundaries, recovery and acceptance checks. The listener is local Unix IPC. Your remote client still needs an independently secured way to reach its local integration; these examples do not expose a public HTTP service.

All default tests are synthetic or mocked. Build and signature checks do not establish real-app consent, locked-session operation, or privacy-grant retention after an upgrade. Validate those properties separately for the exact signed app you intend to install.

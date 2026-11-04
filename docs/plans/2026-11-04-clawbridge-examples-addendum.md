# ClawBridge examples — implementation addendum

Ross requested several simplified reference implementations during the bridge implementation. This extends U5 of the existing approved bridge plan; its settled transport, signing, privacy and release boundaries remain in force.

## Work source

Provide three small, complete adapters using the same reviewed core:

- Keep the synthetic counter/echo adapter as the no-special-permission starting point.
- Add a Music AppleScript adapter with a fixed `com.apple.Music` target and a small fixed action set for playback state and playback control. Request only target-specific Automation when used. Its local scripting dictionary places these operations in `com.apple.Music.playback`; extend build configuration with a validated optional `scripting_targets` map and use that group in the experimental sandbox instead of a whole-target exception. Send static scripts through stdin; expose no caller script, target or executable selection.
- Add a read-only synthetic SQLite catalogue adapter with a compiled, fixed home-relative location, fixed parameterised queries, bounded results and no writes to the source. Reject symlink escapes. It needs no Full Disk Access for its synthetic fixture. Explain how protected real-app data can require that separate grant, and how a sandbox read-only entitlement narrows filesystem access independently.

Each example includes its own build configuration, concise guide, permission explanation and hermetic tests. Tests mock Apple Events and use synthetic SQLite data only; default test guards block both direct AppleScript execution and the Music worker entry point. Extend the explicit standalone export and its guide so all examples are present in the private ClawBridge implementation branch. Keep the core free of app-specific dependencies and avoid a new adapter discovery framework.

## Verification

Test action validation, static AppleScript selection, fixed read-only database access, rejected path/code parameters, symlink handling and configured entitlement targets. Run the full default suite and static checks after all review fixes. Repeat source archives, wheels and signed normal, sandboxed and independently exported synthetic bundle checks on the final implementation. Actual Music control, Things access, privacy grants, installation and locked-session acceptance remain outside this run.

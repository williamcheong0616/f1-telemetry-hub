F1 Telemetry Hub now runs on **Mac** as well as Windows. It's a local telemetry dashboard, race engineer, coach and strategy helper for **EA SPORTS F1 25**, including the **2026 Season Pack**. Everything runs on your own computer; nothing is uploaded anywhere.

## Download

| | File |
|---|---|
| **Windows** 10 or 11 | `F1TelemetryHub.exe` |
| **Mac**, Apple silicon or Intel | `F1TelemetryHub-mac.dmg` |

`SHA256SUMS.txt` lists both files' checksums.

## Get started

**Windows:** put `F1TelemetryHub.exe` in a folder of its own (your history is saved in a `data` folder next to it) and run it. Windows SmartScreen may warn about an unsigned app: **More info → Run anyway**.

**Mac:** open the `.dmg` and drag **F1 Telemetry Hub** onto **Applications**, then open it. The first time, macOS says it could not verify the app, because it isn't signed with an Apple developer account. Click **Done**, then **System Settings → Privacy & Security → Open Anyway**. F1 25 doesn't run on Macs, so the game runs on your PlayStation, Xbox or PC and sends its telemetry to the Mac. The app's window shows the Mac's IP address to use.

**In the game:** **Settings → Telemetry Settings**: UDP Telemetry **On**, Broadcast **Off**, IP **127.0.0.1** if the game runs on the same PC, otherwise the address the app shows; port **20777**, format **2025** (**2026** with the Season Pack), Your Telemetry **Public**. No game handy? **Settings → Demo mode**.

The full **user guide** is in the app (**Guide** in the menu bar) and in [GUIDE.md](https://github.com/williamcheong0616/f1-telemetry-hub/blob/main/GUIDE.md).

## New in 1.1.0

- **Mac app** with its own window: whether telemetry is arriving, the IP address to set in the game, Open dashboard and Quit. History is kept in `~/Library/Application Support/F1 Telemetry Hub`.
- The Live and Settings pages show the right IP address for the game on a Mac.
- While telemetry is arriving, the app keeps the computer from going to sleep, so a laptop next to the console keeps recording through a long race. The screen can still turn off.
- Both downloads are now built and tested automatically on GitHub for every release.

Upgrading from 1.0 on Windows: replace the exe; your history stays in its `data` folder.

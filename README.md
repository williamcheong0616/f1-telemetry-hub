# F1 Telemetry Hub

A local telemetry dashboard and history tracker for **EA SPORTS F1 25**, including the **2026 Season Pack**
("F1 26": UDP format 2026). Formats 2025 and 2024 are understood too.
Everything runs on your own Windows PC or Mac: the game streams UDP packets to the app, the app records them
into a SQLite file, and the dashboard opens in your browser at <http://localhost:8777>. Nothing is uploaded
anywhere.

Live dashboard, race engineer on the radio, corner-by-corner coach with a debrief, setup advisor, race strategy
helper, an engineer's workstation that draws your lap as you drive it, friends' laps to race against, a rig
display for your phone, recordings you can replay, and the history of every lap you have driven.

**[Download the latest release](../../releases/latest)** · **[User guide](GUIDE.md)** (also built into the app)

## Quick start

1. Download from the [latest release](../../releases/latest). There's no Python or anything else to install.
   - **Windows:** `F1TelemetryHub.exe`. Put it in a folder of its own and run it. Windows SmartScreen may warn
     about an unsigned app: click **More info → Run anyway**. A console window shows the dashboard address
     and your PC's IP addresses; the dashboard opens in your browser. Windows Firewall may ask to allow it the
     first time: allow **Private networks** if the game runs on a console or another PC.
   - **Mac** (Apple silicon or Intel): `F1TelemetryHub-mac.dmg`. Open it and drag **F1 Telemetry Hub** to
     **Applications**. F1 25 doesn't run on Macs, so the game runs on a PlayStation, Xbox or PC and sends to
     the Mac. The app isn't signed with an Apple developer account, so the first time macOS says it can't
     verify it: click **Done**, then **System Settings → Privacy & Security → Open Anyway**. The app's
     window shows the dashboard address and the Mac's IP address for the game; the dashboard opens in your
     browser.
2. In the game: **Settings → Telemetry Settings**
   | Setting | Value |
   |---|---|
   | UDP Telemetry | On |
   | UDP Broadcast Mode | Off |
   | UDP IP Address | `127.0.0.1` (same PC) or this computer's LAN IP (console / other PC, and always with a Mac) |
   | UDP Port | `20777` |
   | UDP Send Rate | 20–60 Hz |
   | UDP Format | 2026 with the 2026 Season Pack, otherwise 2025 |
   | Your Telemetry | Public (needed for setups, tyre and damage data of your own car in online sessions) |
3. Drive. Sessions, laps, telemetry and setups are saved automatically.

No game handy? **Settings → Demo mode** (or `F1TelemetryHub.exe --demo race`) streams a simulated race,
qualifying, time trial or career weekend on a fictional "Demo Circuit" through the same pipeline. Demo sessions
can be deleted in one click.

Keep the console window (on a Mac, the app's window) open while you drive; close it or press Ctrl+C (Cmd+Q
on a Mac) to stop. Starting the app again while it runs just opens its dashboard. The [user guide](GUIDE.md)
walks through every page, with recipes and troubleshooting.

## What it does

| Page | What you get |
|---|---|
| **Live** | **Race engineer** radio (see below), **● Record / replay controls**, **race strategy** (pit window, one- vs two-stop), **Rig display** link, session bar (track, laps/time left, weather + forecast, temps, safety car, pit window), car (gear, speed, RPM, pedals, steering, DRS, ERS, fuel, brake bias, TC/ABS), G-force, lap timer with live delta to your PB and session best, purple/green sectors, **micro-sectors** (purple / green / yellow) with your ideal lap, 15 s input trace, track map with every car (static whole circuit or dynamic follow-cam, full window, sectors coloured), timing tower, tyre temps/wear/pressures, damage & PU wear, race-control feed. In Time Trial, a panel with your current lap, session best, the game's personal best and your rival, sector by sector |
| **Sessions** | Every session, filterable by track, session type and game mode (career, championship, time trial, grand prix, online). Per session: result, best/theoretical/average lap, consistency, lap table, lap-time / tyre-wear / fuel / ERS / top-speed charts, classification, positions by lap, tyre strategy for the whole field, all drivers' lap times and pace summary, events, setup, notes, CSV export |
| **Telemetry** | Overlay up to 3 laps (any session, any car you drove): time delta, line vs reference, speed, throttle, brake, gear, steering, RPM and optional ERS, G-forces, tyre/brake temps, suspension, fuel, understeer angle, wheelspin / lock-up, active aero and Overtake Mode (2026 cars). Synced cursor and zoom, racing-line map coloured by lap, by the fastest lap on each 50 m stretch or by inputs, lap comparison table. **Racing line through every corner**: each auto-detected corner gets its own zoomed map with every lap's line, braking point and apex, plus braking point, minimum speed, line at the apex (metres wider / tighter), full-throttle point, exit speed and time gained or lost. Sort corners by the biggest difference |
| **Workstation** | An engineer's screen for one session (see below): micro-sector timeline, stacked traces with time deltas to the reference, the previous lap and the session best, two track maps (gain / loss, speed, inputs or gear, and car balance), lap time deltas and the car's state at the cursor, balance by corner speed, outing report and lap time evolution by tyre stint. Follows the session you are driving, lap by lap, and draws the **lap in progress** against the reference as you drive it |
| **Coach** | Ranked per-corner fixes for a session: where a typical lap loses time against your best (or a friend's) lap and why: braking earlier, slower apex, wider line, later on the throttle. Consistency of braking points, minimum speeds and corner times, and a corner-by-lap heat map. The engineer reads the top three as a debrief |
| **Career** | Driver Career, My Team and championship seasons. Per season: championship position, points, wins, podiums, poles, fastest laps; drivers' and constructors' standings; results by round; points progression; teammate head-to-head (qualifying, race, points); every weekend with links to its sessions. Seasons can be renamed |
| **Tracks & PBs** | Personal bests per circuit and per category (practice / qualifying / race / time trial), theoretical best from your best sectors, progression chart, personal leaderboard, and the game's own Time Trial personal best and rival |
| **Setups** | Every setup you drove, deduplicated and linked to the laps it produced. Rename, favourite, notes, side-by-side compare, copy as text. **Setup advisor**: balance by corner speed and phase, what to change, and what the last change did to balance, tyre temperatures and lap time |
| **Stats** | Distance, time, laps, races, wins, podiums, poles, points, finishing positions, activity |
| **Settings** | Connection diagnostics, units (km/h·mph, °C·°F), theme, recording rate, UDP forwarding to other apps, LAN access, **recordings** (record every session, replay, download, delete, disk cap), **friends' laps**, data folder |
| **Guide** | The [user guide](GUIDE.md), inside the app |

### Captured data vs. the F1 25 UDP spec

All packets are captured: Motion (0), Session (1), Lap Data (2), Event (3), Participants (4), Car Setups (5),
Car Telemetry (6), Car Status (7), Final Classification (8), Car Damage (10), Session History (11),
Tyre Sets (12), Motion Ex (13), Time Trial (14), Lap Positions (15) and, in format 2026, Car Telemetry 2 (16).
A few items from the wish list live in different packets than one might expect:

- **Turbo boost pressure** is not part of the modern F1 UDP spec, so it can't be recorded.
- **Tyre wear and car damage** come from Car Damage (10); **tyre surface/inner temps and pressures** from Car Telemetry (6).
- **Suspension travel/velocity, wheel loads and wheel slip** come from Motion Ex (13), which the game sends for your own car only.
- **DRS activations** per lap are counted from the telemetry DRS flag; the DRSE/DRSD events are race control enabling/disabling DRS.
- Other drivers' setups, tyre data and damage are only available when their telemetry is public.

Lap telemetry is recorded for **your car** at 20 Hz by default (adjustable). Lap times, sectors, positions,
tyre stints and results are recorded for **every car**.

### Career and Time Trial

- **Career seasons** are grouped by the season ID the game sends with every session, and each race weekend
  becomes a round. Restarted sessions count once. Standings are rebuilt from the Final Classification of the
  races the app recorded: **sessions you simulate or skip in the game send no telemetry**, so they are missing
  from the standings, and so are races driven while the app wasn't running. Sprint races count towards points
  and show as a small number next to the race result.
- **Time Trial** uses the game's Time Trial packet: your session best, your personal best as stored by the game
  (including laps set before the app was installed) and your rival, each with its assists. The live panel
  compares your current lap with the rival sector by sector. Your own TT laps are recorded with full telemetry
  like any other session, so they appear in Tracks & PBs and can be overlaid in Telemetry. The rival's lap time
  and sectors are shown; the game doesn't send the rival ghost's telemetry trace.

### F1 26 (2026 Season Pack)

Set **UDP Format to 2026** in the game's telemetry settings. The game keeps format 2025 for existing saves; that
also works, but the game then shows 2026 cars as generic and leaves out the 2026-only data below.

With format 2026 the app also records:

- **24-car arrays** and the new grid: Audi and Cadillac, the 2026 versions of every team, F2 '25/'26 teams and Madrid.
- **Active aero** (corner / straight mode, availability, distance to the next zone) and **Overtake Mode**
  (available, active, distance) from the new Car Telemetry 2 packet. On the Live page they replace the DRS tile
  for 2026 cars; active aero zones are drawn on the track map; laps count straight-mode and Overtake activations;
  both are channels in Telemetry.
- The **ERS harvest limit per lap**, your **start reaction time** in races, ABS / TC assists, collision severity,
  partial-aero and Overtake-Mode race control messages, and a "Wrong way" warning.

Laps in 2026-regulation cars and in older cars are kept apart for the live **Δ personal best**: your PB reference is
always a lap in the same generation of car.

### Race engineer

The Live page has a race engineer who calls what matters while you drive, as text and, when you switch
**Voice on**, spoken with your browser's own voice (with a radio click first). No AI model and no internet:
every message comes from a fixed rule over the data the game sends, so it is instant and only quotes the
game's numbers. Messages wait for a straight (full throttle, no brake, wheel straight) so the engineer never
talks while you brake or turn in; safety cars, flags, penalties and serious damage are called at once.

| Messages | What you hear |
|---|---|
| Lap times | Every flying lap in practice, qualifying and Time Trial against your personal best, the corner where you lost most (named C1, C2... as on the Telemetry page), best of the session, micro-sector records and your new ideal lap. In races: fastest lap and personal-best race laps |
| Sector and micro-sector calls | At the end of sectors 1 and 2 (not in races): time to your PB lap and how many micro-sector records you set |
| Gaps and positions | Races: the cars ahead and behind within a second, gaining or closing in, a gap update every few laps, overtakes, DRS / Overtake Mode available, rejoining after a stop |
| Fuel and battery | Races: fuel plus/minus laps when it changes (push, on target, lift and coast) and a low battery |
| Tyres, pit window and strategy | Overheating or cold tyres, wear at 40 / 60 / 75 %, pit window open and its last lap; the strategy helper's plan, its window opening and the lap to box on |
| Weather | Rain coming in the next 15 minutes (with its chance), rain starting, getting heavier or stopping |
| Flags, penalties and damage | Safety car / VSC deployed and ending, red, yellow and blue flags, time penalties, drive-throughs, warnings, invalidated laps, wing / floor / tyre damage, DRS / ERS faults |
| Session | Radio check, minutes left in practice and qualifying, last lap, chequered flag with your position and points |
| Debrief | Back in the garage or at the end of a session: the three corners where a typical lap loses most, and why |

**Messages** chooses which kinds you get, the voice and its speed, the radio click, and a tone for every
micro-sector. These are remembered per device, so a phone or tablet next to the screen (with LAN access
on) can do the talking. Browsers keep a page silent until you have clicked on it once.

### Micro-sectors

Every sector is split into 8 equal stretches (24 per lap), timed live and stored with each lap:

- **purple**: your own record for that stretch, the quickest you have ever been there over every valid lap on
  this track in this kind of session (and generation of car);
- **green**: at least as quick as your personal-best lap there;
- **yellow**: slower than your personal-best lap.

Stretches you haven't reached yet this lap show the last lap faded. **Ideal lap** adds up your records. Laps
recorded before micro-sectors existed are timed from their telemetry the first time you drive that track
again, so your records start from your whole history. Invalid laps, out laps and in laps never set records.

### Workstation

The Workstation page puts everything about one lap on one screen, like a team's data engineer would have it.
Pick a session, a lap and a reference (by default the best lap of the session; when the lap *is* the best,
your best before it on this track). On the session you are driving it follows along and moves to every new
lap as you complete it.

- **One cursor for everything**: hover a trace or either track map and every panel follows. Drag across a
  trace to zoom, double-click to zoom out; click a micro-sector to zoom to it.
- **Micro-sector timeline**: the lap's 24 micro-sectors, purple for the session's best, green where it beat
  the reference, yellow where it didn't, with the difference written in each; sector and lap times beside it.
- **Traces**: time delta to the reference, the lap before and the session best, then speed, throttle, brake,
  gear, steering, understeer angle and wheelspin / lock-up (more under **Channels**; the choice is remembered).
- **Track map** coloured by where the lap gains or loses time against the reference (over each 25 m), by
  speed, by inputs or by gear, and **Balance on track** coloured by the understeer angle in the corners.
- **Lap time deltas** and **Car at cursor**: the deltas at that point of the lap; speed, gear, RPM, pedals,
  battery, fuel and each tyre's surface and inner temperature, pressure, brake temperature and wear.
- **Balance by corner speed**: the understeer angle of every cornering sample against speed, with the average
  per speed band, so you can see whether the car pushes in slow corners or gets loose in fast ones.
- **Outing report** (every lap with sectors, session-best sectors in purple, tyre, top speed and fuel used;
  click a lap to load it, **Ref** to compare against it) and **lap time evolution** per tyre stint, with the
  trend in seconds per lap.

The **understeer angle** is how much more the front tyres slip sideways than the rears (from the game's
Motion Ex data): above zero the car understeers, below zero it oversteers. Wheelspin and lock-up come from
the wheels' slip ratios. Laps recorded before this version don't have these three channels.

### Corner coach and debrief

**Coach** compares every clean lap of a session (flying, complete, within 107 % of the best) with a reference:
the session's best lap, your all-time best at the circuit or a friend's lap. For every corner it measures the
time lost and the braking point, minimum speed, line at the apex, full-throttle point and exit speed, and
ranks the corners by what a *typical* lap (the median) loses there. The top three become plain-language
fixes, e.g. *Corner 7: losing 0.18 s on a typical lap. You brake 12 m earlier and are back on full throttle
20 m later. Your minimum speed is fine.* It also shows how consistent each corner is (braking point, minimum
speed and time from lap to lap) and a heat map of every corner on every lap. The engineer reads the top
three when you return to the garage or the session ends.

### Setup advisor

Under every setup on **Setups**: the car's balance (understeer angle from Motion Ex) in slow, medium and fast
corners and on entry, mid-corner and exit, wheelspin, lock-ups and front/rear tyre temperatures, then
suggestions with the exact clicks (*oversteer in slow corners → rear anti-roll bar 6 → 4*). For the setup you
drove before it, it shows what you changed and what that did to the balance, tyre temperatures and your best
and typical lap times, flagging comparisons made in different conditions.

### Race strategy

In races, the **Strategy** card on the Live page fits your tyres' drop-off and wear rate from this race's laps
(fuel effect removed), takes the other compounds' pace and life from the game's tyre-set data, and tries
every one- and two-stop plan with the sets you have left and the two-compound rule. It shows the lap to box
on, the window within a second of it, each plan's cost, and the model behind it; the pit loss starts at 22 s,
is measured from your own stop, and can be typed in.

### Friends' laps

**Export lap** on a session's lap table saves a `.f1lap` file (the lap's telemetry, times and setup, gzipped,
typically under 100 KB). A friend imports it with **Import a friend's lap** (Settings, or the Telemetry
lap picker) and can pick it as the reference on Telemetry, the Workstation and the Coach, including the
Workstation's lap-in-progress delta while they drive. Imported files are validated field by field.

### Rig display

`#/rig` (**Rig display** on the Live page) is a stripped-down screen for a phone or tablet on the wheel: a
big live delta (tap to switch between your PB and the session best) with a bar, the micro-sectors, lap time,
gear and speed. With **LAN access** on, open `http://<PC IP>:8777/#/rig` on the phone.

### Recordings & replay

A recording keeps everything the game sends, exactly as it arrives, so a session can be played again later.

- **Record**: press **● Record** at the top of the Live page (press again to stop), or tick **Settings →
  Recordings → Record every session automatically**. Each game session (practice, qualifying, race…) goes
  into its own file in `data\recordings`; the demo is never recorded.
- **Replay**: **▶ Replay** on a session's page, or in **Settings → Recordings**. The recording plays on the
  Live page as if you were driving it, race engineer and micro-sectors included, with play / pause,
  0.5× to 16× speed and a slider to jump anywhere. A replay runs against a copy of your history taken when it
  starts, so personal bests and records are the ones you had on the day, and **nothing it does is saved**:
  your sessions, laps and records stay exactly as they were. While a replay plays, the game's live data is
  still saved as normal; only the Live page shows the replay.
- **Size**: the game sends about 230 MB per 10 minutes at a 60 Hz send rate; recordings are compressed,
  so expect something like 50-80 MB per 10 minutes of a race (an estimate until measured on the real game;
  half that at 30 Hz, much less in Time Trial). **Keep up to** (2-100 GB, 5 GB by default) caps the folder;
  when it is full the oldest recordings are deleted, never the one being written or replayed.
- **Sharing**: **Download** gives you the `.f1rec` file. Someone with this app can drop it into their own
  `data\recordings` folder and replay it; it's also the easiest way to report something the app got wrong.

### Track maps

The game never sends a circuit's layout, so the app ships outlines of every track in F1 25 / F1 26
(the 2026 Madrid circuit and the reverse layouts included; not the short layouts or Hanoi). The full map
is there the moment a session starts, north-up like the real circuit:

1. Until you have driven a few corners, cars are placed on the outline by lap distance ("Approximate positions").
2. After roughly 700 m with some corners, the app works out how the game's coordinates sit on the outline
   (turn, mirror, shift and where the start line is) and from then on draws every car where it really is.
   That alignment is stored per track, so the next session on that circuit is lined up from the first metre.
3. After your first full valid lap the map uses the line you actually drove; Telemetry, Tracks & PBs and
   the corner maps use the same north-up orientation. If a game update ever moves a track, the app notices
   on the next lap and lines it up again.

Tracks without a bundled outline (and the Demo Circuit) work as before: the map appears after the first lap.

### Notes

- Flashbacks are handled: the telemetry after the rewind point is discarded, and laps rewound across the line are re-recorded.
- Time Trial run-ups and **Restart lap** are handled: a lap starts where the game starts timing it, so the
  run-up and any abandoned attempt are left out, and the first lap from the run-up counts like any other.
  Laps recorded before this was fixed are cleaned up when they are read, and a track map with a hole in it
  is redrawn from your best laps.
- Out-laps are marked invalid outside races so they never become a PB.
- Packet sizes are checked against the spec of the format the game sends (2025 or 2026). If a game update
  changes one, **Settings → Game connection** shows an "Unexpected packet sizes" warning naming it.
- Another telemetry app (SimHub, a wheel display…) can keep working: add it under **Settings → Forward UDP to**
  (e.g. `127.0.0.1:20778`) and point that app at the new port.

## Data

History lives in `data\f1telemetry.db` next to the exe (`--data-dir` or the `F1TH_DATA_DIR` environment
variable to move it), recordings in `data\recordings`. If the exe's folder can't be written to (Program Files),
the data goes to `%LOCALAPPDATA%\F1TelemetryHub\data` instead. The Mac app keeps it in
`~/Library/Application Support/F1 Telemetry Hub`, with `app.log` (what a console would show). Copy that folder
to back up or move your history. **Settings → Data** opens it.

## Command line

```
F1TelemetryHub.exe [--udp-port 20777] [--http-port 8777] [--data-dir PATH] [--no-browser]
                   [--demo race|quali|tt|weekend] [--demo-format 2025|2026] [--demo-laps N] [--demo-speed X]
```

On a Mac the program is `"/Applications/F1 Telemetry Hub.app/Contents/MacOS/F1TelemetryHub"`; `--no-window`
runs it in the terminal without the app's window. `--udp-port`/`--http-port` apply to that run only; the
Settings page stores permanent changes. With
**LAN access** enabled, the dashboard is also reachable from a phone or tablet at `http://<PC IP>:8777`.

## Run from source / build the apps

The app uses only the Python standard library (Tk for the Mac app's window); PyInstaller is needed only to
build the exe and the Mac app.

```
conda env create -f environment.yml
conda activate f1-telemetry
python run.py
```

`build_exe.bat` builds `dist\F1TelemetryHub.exe` from the `f1-telemetry` conda env (set `F1TH_PYTHON` to use
another interpreter). Close the running app first: Windows can't replace an exe that is in use. `python -m f1telemetry.simulator --session race --laps 5 [--format 2026]` streams demo
packets to port 20777 for testing against a running app; `--circuit 7` drives a real circuit from the bundled
outlines instead (stored under that track id, so point it at an app with a separate `--data-dir`), and
`--session tt --restart-lap 2` does a Time Trial "Restart lap" early in lap 2.
`build_mac.sh` builds `dist/F1 Telemetry Hub.app` and `dist/F1TelemetryHub-mac.dmg` on a Mac from
`packaging/macos.spec`. Use the python.org installer's Python for an app that runs on Apple silicon and Intel
Macs. GitHub Actions (`.github/workflows/build.yml`) builds both on every push and tests them with
`tools/smoke_test.py`, which starts a build, drives a simulated race into it and checks what it saved. A
version tag (`v1.2.3`) puts both on a draft release.
`tools\make_icon.py` regenerates `assets\app.ico` and `assets\app.icns`; `tools\make_circuits.py` rebuilds
`f1telemetry\circuits.json` from the f1-circuits GeoJSON.

Layout: `f1telemetry/packets.py` (UDP parser), `recorder.py` (live state + lap recording), `storage.py`
(SQLite), `server.py` (HTTP API + live stream), `app.py` (entry point, settings, UDP listener), `window.py`
(the Mac app's window),
`career.py` (seasons and standings), `circuits.py` (bundled track outlines and lining them up),
`engineer.py` (race engineer rules), `micro.py` (micro-sector timing and records), `recordings.py`
(recording the raw packets and replaying them), `coach.py` (corner coach), `advisor.py` (setup advisor),
`strategy.py` (race strategy), `lapfile.py` (`.f1lap` export and import), `simulator.py`
(demo packets), `web/` (dashboard: plain JS modules, no CDN, works offline). `GUIDE.md` is the user guide,
bundled into the exe and shown on the Guide page.

## Credits

Circuit outlines: [f1-circuits](https://github.com/bacinger/f1-circuits) by Tomislav Bacinger, MIT licence
(the licence text is included in `f1telemetry/circuits.json`).

F1 Telemetry Hub is released under the [MIT licence](LICENSE). It is a fan-made tool, not affiliated with or endorsed by
EA, Codemasters, Formula 1 or the FIA; F1 and related marks belong to their owners.

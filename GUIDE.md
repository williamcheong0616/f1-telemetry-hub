# F1 Telemetry Hub user guide

F1 Telemetry Hub records everything **EA SPORTS F1 25** (and its **2026 Season Pack**) sends over UDP while
you drive, and turns it into a live dashboard, a race engineer on the radio, a corner-by-corner coach, a
setup advisor, a race strategy helper and a history of every lap you have driven. It runs on your own
Windows PC or Mac and works without an internet connection. Nothing is uploaded anywhere.

This guide covers installing it, connecting the game, every page, step-by-step recipes for the common jobs,
what the numbers mean, and what to do when something doesn't work. The same guide is built into the app:
click **Guide** in the menu bar.

## Contents

- [Install and first start](#install-and-first-start)
- [Connect the game](#connect-the-game)
- [Try it without the game](#try-it-without-the-game)
- [The pages](#the-pages)
- [Recipes](#recipes)
- [What the numbers mean](#what-the-numbers-mean)
- [Troubleshooting](#troubleshooting)
- [Your data](#your-data)
- [Command line](#command-line)

## Install and first start

### What you need

- A Windows 10 or 11 PC, or a Mac (Apple silicon or Intel).
  - On Windows, the game can run on the same PC, on a console (PlayStation, Xbox) or on another PC on the
    same network.
  - F1 25 doesn't run on Macs, so with a Mac the game runs on a console or a PC on the same network and sends
    its telemetry to the Mac.
- EA SPORTS F1 25. The 2026 Season Pack is supported, and so are the 2024 and 2025 UDP formats.
- A browser (Edge, Chrome, Firefox or Safari). The dashboard is a web page served by the app on your
  computer.

Nothing else: no Python, no installer, no account.

### Download

Open the project's GitHub page, go to **Releases** and download from the latest release:

- **Windows:** `F1TelemetryHub.exe`. Make a folder for it, for example `Documents\F1 Telemetry Hub`, and put
  the exe there. The app keeps its history in a `data` folder next to the exe, so a folder of its own keeps
  things tidy. (Downloads works too, but the data folder ends up in Downloads.)
- **Mac:** `F1TelemetryHub-mac.dmg`. Open it and drag **F1 Telemetry Hub** onto **Applications**. The same
  app runs on Apple silicon and Intel Macs. Its history goes in your Library folder (see
  [Your data](#your-data)), so it doesn't matter where the app itself is.

### First start on Windows

1. Double-click `F1TelemetryHub.exe`.
2. **Windows SmartScreen** may say *Windows protected your PC*, because the exe isn't signed with a paid
   certificate. Click **More info**, then **Run anyway**. You only see this once per download.
3. A console window opens with the dashboard address, the telemetry port and the game settings to use.
   Your browser opens the dashboard at `http://localhost:8777`.
4. **Windows Firewall** may ask whether to allow the app. If the game runs on the same PC you can click
   **Cancel**; nothing needs to come in from outside. If the game runs on a **console or another PC**, or you
   want to open the dashboard on a phone, allow it on **Private networks**.

> Keep the console window open while you drive: it *is* the app. Close it (or press Ctrl+C in it) to stop.
> Starting the exe again while it is already running just opens the dashboard of the one that is running.

### First start on a Mac

1. Open **F1 Telemetry Hub** from Applications.
2. The first time, macOS says it *could not verify* that the app is free of malware, because the app isn't
   signed with a paid Apple developer account. Click **Done**, open **System Settings → Privacy & Security**,
   scroll down to the message about F1 Telemetry Hub and click **Open Anyway**, then confirm. You only do
   this once per version. (On macOS 14 Sonoma and older, right-click the app, choose **Open**, then **Open**
   again.)
3. The app's window opens. It shows whether telemetry is arriving, the dashboard address, the settings to
   use in the game, with this Mac's IP address, and where your data is. Your browser opens the dashboard at
   `http://localhost:8777`.
4. If you've turned on the macOS firewall, it may ask whether the app can accept incoming network
   connections: click **Allow**, or the console's data can't reach it.

> Keep the app's window open while you drive: closing it, or **Cmd+Q**, quits the app. If the window is
> behind others, click the app's icon in the Dock.

### Updating

- **Windows:** download the new `F1TelemetryHub.exe`, close the running app, and replace the old exe with the
  new one. Your history stays in the `data` folder next to it.
- **Mac:** quit the app, open the new `.dmg` and drag the app onto **Applications** again, choosing
  **Replace**. Then open it as on the first start (**Open Anyway** again, once). Your history stays where it
  is.

Your history is upgraded automatically the first time the new version starts.

### Uninstalling

- **Windows:** close the app and delete its folder. That removes everything: the app keeps nothing in the
  registry or anywhere else. (If the exe was in a folder Windows doesn't let it write to, such as
  `Program Files`, its data is in `%LOCALAPPDATA%\F1TelemetryHub\data` instead; delete that too.)
- **Mac:** quit the app and drag it from Applications to the Bin. To delete your history too, open
  **Finder → Go → Go to Folder…**, enter `~/Library/Application Support` and delete the
  **F1 Telemetry Hub** folder.

## Connect the game

### Game settings

In the game: **Settings → Telemetry Settings**.

| Setting | Value |
|---|---|
| UDP Telemetry | On |
| UDP Broadcast Mode | Off |
| UDP IP Address | `127.0.0.1` when the game runs on this PC; this computer's IP address when the game runs on a console or another PC (always the case with a Mac) |
| UDP Port | `20777` (the number the app's console or window and **Settings** show) |
| UDP Send Rate | 20 to 60 Hz. 60 gives the smoothest traces; 30 is plenty |
| UDP Format | **2026** with the 2026 Season Pack, otherwise **2025** |
| Your Telemetry | **Public**: without it the game leaves out your own car's setup, tyre and damage data in online sessions |

### Same PC or another device

- **Same PC:** use `127.0.0.1`.
- **Console or another PC:** the console window lists this PC's IP addresses (also shown on the Live page
  while it waits, and in **Settings → Game connection**). Use the one on the same network as the console,
  usually starting `192.168.` or `10.`, and allow the app through the firewall on Private networks.
- **Mac:** the game always runs on a console or a PC. Use the IP address the app's window shows (also on the
  Live page and in **Settings → Game connection**). macOS doesn't ask for permission to receive it. Keep
  **UDP Broadcast Mode** Off: a broadcast needs the Local Network permission.

While telemetry is arriving, the app stops the computer from going to sleep by itself, so a laptop next to the
console keeps recording through a long race. The screen can still turn off. Five minutes after the data stops,
the computer can sleep again as usual.

### Is it working?

The pill at the top right of every page shows the connection:

| Pill | Meaning |
|---|---|
| Waiting for game | Nothing has arrived yet. Check the settings above, and that the game is past its menus |
| Receiving · 60 pkt/s | Telemetry is arriving |
| Demo · ... / Replay · ... | The demo or a recording is playing |
| UDP port unavailable | Another program is using the port: see [Troubleshooting](#troubleshooting) |

**Settings → Game connection** shows the details: packets per second, the game's UDP format, and a warning
if the packets don't match the format the game is set to.

### Other telemetry apps at the same time

The game sends to one address and port only. To keep SimHub, a wheel display or another tool working, point
the game at this app and add the other tool under **Settings → Preferences → Forward UDP to**, for example
`127.0.0.1:20778`, then set that tool to listen on 20778. The app passes every packet on unchanged.

## Try it without the game

**Settings → Demo mode** streams a simulated session through the same pipeline as the real game: a race,
qualifying, a time trial or a career weekend, in the 2025 or 2026 format, on a fictional *Demo Circuit*.
Everything works on demo data, including the engineer, the coach and the strategy helper. Demo sessions are
marked as such and **Delete demo data** removes them in one click.

## The pages

The menu bar along the top: **Live, Sessions, Career, Telemetry, Workstation, Coach, Tracks & PBs, Setups,
Stats, Settings, Guide.**

### Live

The dashboard while you drive. It appears as soon as you are on track.

- **Session bar:** circuit, session type, lap (or time left), weather and forecast, track and air temperature,
  safety car status and the game's pit window.
- **Car:** gear, speed, RPM and rev bar, throttle, brake and clutch, steering, DRS (or Overtake Mode on 2026
  cars), battery and deployment, fuel, fuel mix, brake bias, engine temperature, TC / ABS. **G-force** below.
- **Lap:** position, the running lap time, the live delta to your personal best and to the session best,
  sector times in purple (best of the session) / green (your best) / yellow, the **micro-sectors** of this lap
  and your **ideal lap**, then last lap, session best, personal best and the gaps.
- **Track map:** every car on the circuit, sectors coloured. **Static** shows the whole circuit, **Dynamic**
  follows your car (with zoom); **Full window** fills the screen (Esc to leave).
- **Inputs · last 15 s:** speed, throttle and brake as a scrolling trace.
- **Timing:** the order, gaps, last and best laps, tyres and pit stops. In Time Trial, a panel with your lap,
  the session best, the game's personal best and your rival, sector by sector.
- **Tyres:** each tyre's surface and inner temperature, pressure, wear and brake temperature, plus the tyre
  sets you have left.
- **Strategy** (races only): when to stop and on which tyres. See [Strategy helper](#strategy-helper).
- **Damage & power unit**, and **Race control** (flags, penalties, fastest laps, retirements).
- **Race engineer** radio, top right. See [Race engineer](#race-engineer).
- At the very top: **● Record** (see [Recordings and replay](#recordings-and-replay)) and **Rig display**
  (see [Rig display](#rig-display)).

### Race engineer

The engineer calls what matters while you drive, as text in the radio panel and, with **Voice on**, spoken
by your browser (with a radio click first). It uses no AI service and no internet: every message is a fixed
rule over the game's own numbers, so it is instant. Messages wait for a straight (full throttle, no brake,
wheel straight) so it never talks while you brake or turn in; safety cars, flags, penalties and serious
damage are called at once.

| Kind | What you hear |
|---|---|
| Lap times | Every flying lap outside races against your personal best, the corner where you lost most, session bests, micro-sector records and a new ideal lap. In races: fastest laps and personal-best race laps |
| Sector and micro-sector calls | End of sectors 1 and 2 (not in races): the gap to your PB lap and how many micro-sector records you set |
| Gaps and positions | Races: the cars ahead and behind within a second, closing or pulling away, a gap update every few laps, overtakes, DRS / Overtake Mode available, rejoining after a stop |
| Fuel and battery | Races: fuel plus/minus laps when it changes, low battery |
| Tyres, pit window and strategy | Overheating or cold tyres, wear at 40 / 60 / 75 %, the game's pit window, and the strategy helper's plan, its window opening and the lap to box on |
| Weather | Rain in the next 15 minutes with its chance, rain starting, getting heavier or stopping |
| Flags, penalties and damage | Safety car / VSC, red, yellow and blue flags, penalties, warnings, invalidated laps, wing / floor / tyre damage, DRS / ERS faults |
| Session | Radio check, minutes left in practice and qualifying, last lap, chequered flag with your position and points |
| Debrief | When you go back to the garage or the session ends, with three or more laps saved: the three corners where a typical lap loses most, and why |

**Messages** chooses the kinds you want, the voice and its speed, the radio click, and an optional tone for
every micro-sector (two high beeps for a record, one for faster than your PB lap, a low one for slower).
These choices are stored per device, so a phone or tablet beside the screen can do the talking while the PC
stays quiet.

> Browsers don't play sound on a page until you have clicked it once. If the voice is silent, click anywhere
> on the Live page.

### Rig display

A stripped-down screen for a phone or tablet mounted on the wheel or the monitor stand: a huge live delta
with a bar, the 24 micro-sectors, the lap time, gear and speed, and below them the last lap, your best and
your position. Open it with **Rig display** at the top of the Live page, or go to `#/rig`.

- **Tap the delta** to switch between your personal best and the session best.
- **Full screen** hides the browser's bars. **Screen stays on** keeps the phone awake while the page is open
  (browsers only allow that on the PC itself or over https; on a phone over Wi-Fi, set the phone's screen
  timeout to *never* while you drive instead).
- To open it on a phone, see [Use a phone on the rig](#use-a-phone-on-the-rig).

### Sessions

Every session you have driven, newest first, filterable by circuit, session type and game mode (career,
championship, time trial, grand prix, online). Click one to open it:

- **Laps:** every lap with sectors, tyre, wear, fuel, top speed, position and validity. **Telemetry** opens
  the lap on the Telemetry page; **Export lap** saves it as a `.f1lap` file for a friend (see
  [Race a friend's lap](#race-a-friends-lap)). Tick laps and **Compare telemetry** to overlay them.
- **Charts:** lap times, tyre wear, fuel, battery and top speed over the session.
- Races add the classification, positions by lap, every driver's tyre strategy and lap times, and a pace
  summary.
- **Events**, the **Setup** you drove and your own **Notes**.
- At the top: **Workstation**, **Coach**, **▶ Replay** (when the session was recorded), **Export CSV** and delete.

### Telemetry

Overlay up to three laps from any session, at any circuit you drove. The first lap is the **reference**;
**⇤** makes another lap the reference and **×** removes it. **+ Add lap** picks another lap, including your
friends' laps.

- **Channels:** time delta, line versus the reference (metres left / right), speed, throttle, brake, gear,
  steering and RPM, plus battery, G-forces, tyre and brake temperatures, suspension, fuel, understeer angle,
  wheelspin and lock-up, and active aero / Overtake Mode on 2026 cars.
- **One cursor and zoom for everything:** hover a chart and every chart and the map follow. Drag across a
  chart to zoom in, double-click (or **Reset zoom**) to zoom out.
- **Racing-line map** coloured by lap, by which lap was quickest on each 50 m stretch, or by inputs.
- **Corners:** every corner gets its own zoomed map with each lap's line, braking point and apex, plus the
  braking point, minimum speed, line at the apex (metres wider or tighter), full-throttle point, exit speed
  and time gained or lost. Sort by the biggest difference to find where the time is.
- **CSV lap N** downloads a lap's raw samples for a spreadsheet.

### Workstation

Everything about one lap on one screen, the way a team's data engineer would have it. Pick a **session**, a
**lap** and a **reference** (by default the session's best lap; when the lap *is* the best, your best before it
at this circuit; or a friend's lap).

- **Lap in progress** (on the session you are driving): the lap you are on, drawn as you drive it, against
  the reference: the time delta, speed, throttle and brake, the line so far on a small map (green where you
  are gaining, red where you are losing), and the lap time, delta, predicted lap time and how far round you
  are. **Lap in progress** in the toolbar hides or shows it.
- **Following live:** on the session you are driving, the page moves to each lap as you complete it.
  Pick an older lap to stop following; **Follow live** starts again.
- **Micro-sector timeline** with the difference in each, sector and lap times beside it. Click a
  micro-sector to zoom the traces to it.
- **Traces:** time delta to the reference, the lap before and the session best, then the channels you choose
  under **Channels** (remembered).
- **Track map** coloured by gain / loss against the reference, by speed, by inputs or by gear, and **Balance
  on track** coloured by understeer and oversteer.
- **Lap time deltas** and **Car at cursor**: speed, gear, pedals, battery, fuel and every tyre's temperatures,
  pressure, brake temperature and wear at the point under the cursor.
- **Balance by corner speed:** whether the car pushes in slow corners or gets loose in fast ones.
- **Outing report:** every lap with sectors and tyre (click to load, **Ref** to compare against), and **lap
  time evolution** per tyre stint with the trend in seconds per lap.

### Coach

Where a typical lap of a session loses time against your best lap, corner by corner, and how consistent you
are. Pick the **session** and what to **compare with**: the session's best lap, your all-time best at the
circuit, or a friend's lap.

- **Tiles:** the reference lap, your **typical lap** (the median of the session's clean laps), the **best of
  every corner** put together, and your **consistency** (lap time spread).
- **What to work on:** the three corners that cost the most on a typical lap, each with what you do
  differently there, in plain words. For example: *Corner 7: losing 0.18 s on a typical lap. You brake 12 m
  earlier and are back on full throttle 20 m later. Your minimum speed is fine.* **Telemetry** opens the
  reference and the typical lap together.
- **Every corner:** the time lost on a typical lap, braking point, minimum speed, line, full-throttle point and
  exit speed against the reference, how much the time, braking point and minimum speed vary from lap to lap,
  and which lap was best there.
- **Every corner, every lap:** a grid of the time each lap lost (red) or gained (green) in each corner, so a
  mistake or a corner you never get right stands out. The least consistent corners are named below it.

The coach only uses laps that say something about your pace: flying laps with complete telemetry, within
107 % of the best lap. It needs at least two.

### Setups

Every setup you have driven, saved automatically and only once however many laps you do with it, linked to
the laps it produced. **Rename**, **favourite** and add **notes**; **compare** two side by side; **copy** a setup
as text to share it.

#### Setup advisor

Open a setup and the **Setup advisor** below it reads its laps:

- **Balance:** the average understeer angle in slow (under 120 km/h), medium and fast (over 200 km/h)
  corners, and on corner entry (braking), mid-corner and exit (on the power). Bars to the right are
  understeer (the front pushes wide), to the left oversteer (the rear slides).
- Wheelspin out of slow corners, lock-ups under braking, and front and rear tyre surface temperatures.
- **What to try:** the changes that address the biggest problem first, each with the exact clicks, for
  example *Understeer in slow corners → Front anti-roll bar 12 → 10*.
- **What changed from the previous setup, and what it did:** the settings you changed, and the effect on
  the balance in each kind of corner, on wheelspin, lock-ups, tyre temperatures and on your best and typical
  lap times. If the two setups were driven in different conditions (tyres, weather, track temperature or a
  different kind of session), it says so: such comparisons are only a hint.

See [Tune a setup](#tune-a-setup) for the way to use it.

### Strategy helper

In races, the **Strategy** card on the Live page plans your stops from the lap you are on to the flag.

- **The headline:** the lap to box on for the quickest plan, and the **window**: every lap you could box on
  for that tyre and lose less than a second overall.
- **The plans:** the best plan with one stop and with two stops (and staying out, when the rules allow),
  each with its tyres, the laps of each stint and the laps to box on, and how much slower it is than the best.
- **Your tyres:** the fitted set's age, wear, how fast it is wearing, how much time it is losing per lap, and
  roughly when it will be done.
- **The model:** for each dry compound, the drop-off (seconds lost per lap for every lap of tyre age), the
  pace of a new set against your fitted compound, its life and how many sets you have left.
- **Pit stop costs:** the time a stop costs against staying out. It starts at 22 s, is measured from your
  own stop once you have made one, and you can type your own.

How it works: the drop-off and wear rate of your fitted tyres are measured from your laps in this race (with
the effect of the fuel burning off taken out). The other compounds' pace and life come from the game's tyre
set data, and their drop-off is scaled from yours. Every plan with one or two stops is then tried, using the
sets you actually have and the two-compound rule in dry races. It assumes a clean race: a safety car, rain or
damage changes everything. The engineer reads out the plan after a few laps, when the window opens, and on
the lap to box.

### Career

Driver Career, My Team and championship seasons, each with your championship position, points, wins,
podiums, poles and fastest laps, the drivers' and constructors' standings, results by round, points
progression and your head-to-head with your teammate. Every weekend links to its sessions. Seasons can be
renamed.

### Tracks & PBs

Your personal best at every circuit, per kind of session (practice, qualifying, race, time trial), the
theoretical best from your best sectors, how your best has come down over time, your fastest laps there,
and the game's own Time Trial personal best and rival.

### Stats

Distance, driving time, laps, races, wins, podiums, poles, points, finishing positions and activity.

### Settings

- **Game connection:** the settings to use in the game, this PC's IP addresses and the live connection
  details.
- **Demo mode:** see [Try it without the game](#try-it-without-the-game).
- **Preferences:** UDP port, **recording rate** (telemetry samples stored per second), speed unit (km/h or
  mph), temperature unit (°C or °F), theme (dark, light or follow Windows), **Forward UDP to**, dashboard
  port, **Allow LAN access** (needed for phones and tablets; restart the app after changing it) and whether to
  open the dashboard when the app starts.
- **Recordings:** see [Recordings and replay](#recordings-and-replay).
- **Friends' laps:** every lap you have imported, to open or delete, and **Import a friend's lap**.
- **Data:** where your history is, how big it is, and **Open data folder**.

### Recordings and replay

A recording keeps everything the game sends, exactly as it arrives, so a session can be played again later.

- **Record:** press **● Record** at the top of the Live page (press again to stop), or tick **Settings →
  Recordings → Record every session automatically**. Each session goes into its own `.f1rec` file in
  `data\recordings`. The demo is never recorded.
- **Replay:** **▶ Replay** on a session's page, or in **Settings → Recordings**. It plays on the Live page as
  if you were driving it, engineer and micro-sectors included, with play / pause, 0.5× to 16× speed and a
  slider to jump anywhere. A replay never changes your history: your sessions, laps and records stay exactly
  as they were. While a replay plays, the game's live data is still saved as normal.
- **Size:** expect roughly 50 to 80 MB per 10 minutes of a race at a 60 Hz send rate (half that at 30 Hz,
  much less in Time Trial). **Keep up to** caps the folder (5 GB by default); when it is full, the oldest
  recordings are deleted first.
- **Sharing:** **Download** gives you the `.f1rec` file. Someone else with this app can put it in their own
  `data\recordings` folder and replay it.

## Recipes

### Find time in a qualifying session

1. Drive a run of at least four or five flying laps.
2. Listen to the debrief when you go back to the garage, or open **Coach** for the session.
3. Read **What to work on**: three corners, each with what you do differently from your best lap there.
4. Click **Telemetry** on a fix to see your best and your typical lap overlaid; the corner's card shows both
   lines, the braking points and the apex.
5. Look at **Every corner, every lap**: a corner that is red on only one lap was a mistake; a corner that is
   red on most laps is the one to practise.
6. Go out again and work on one corner at a time. On the **Workstation**, **Lap in progress** shows straight
   away whether the new approach is gaining.

### Tune a setup

1. Drive four or more clean laps with your current setup (the advisor needs some corners of each speed).
2. Open **Setups**, pick that setup (the newest is at the top) and read the **Setup advisor**.
3. Make **one** of the suggested changes in the game's setup screen, or one change of your own.
4. Drive another four or more laps. The app saves the new setup by itself.
5. Open the new setup: **What changed and what it did** shows whether the balance moved the way you wanted,
   and what it did to your lap times. Keep it, or go back and try the next suggestion.

Change one thing at a time: with two changes at once you can't tell which one did what.

### Plan a race

1. Before the race, open the Live page; the **Strategy** card appears when the race starts.
2. For the first laps the plan uses typical values. From about lap 5 it uses your own drop-off and wear.
3. If you know the pit loss at this circuit, type it into **Pit stop costs** (it's remembered on this device).
4. Watch the window: the engineer tells you when it opens and on which lap to box. A wide window means there
   is no hurry; use it to stop when you have clean air or to react to the cars around you.
5. After your stop, the card plans the rest of the race from your new tyres, with the pit loss now measured.

### Race a friend's lap

1. Your friend opens the session on **Sessions**, and clicks **Export lap** on the lap to share. They get a
   small `.f1lap` file (a lap's telemetry, its times and the setup) and send it to you.
2. You click **Import a friend's lap** (in **Settings → Friends' laps**, or in the Telemetry page's lap
   picker) and choose the file.
3. Compare: on **Telemetry**, add the friend's lap; on the **Workstation** or the **Coach**, pick it as the
   reference. The Workstation's **Lap in progress** then shows you gaining or losing on their lap as you
   drive.

The file contains your in-game name, the lap and your setup for it, nothing else. Files are checked when they
are imported, so a damaged or tampered file is refused.

### Use a phone on the rig

1. On the PC: **Settings → Preferences → Allow LAN access**, **Save settings**, then restart the app. Allow it through
   Windows Firewall on Private networks if Windows asks.
2. Make sure the phone is on the same Wi-Fi as the PC.
3. Open **Rig display** on the PC. At the top it shows the address to type on the phone, something like
   `http://192.168.1.20:8777/#/rig`.
4. On the phone, open that address. Tap **Full screen**. Add it to the home screen to open it with one tap.
5. A phone or tablet can also show the whole dashboard (`http://192.168.1.20:8777/`), and do the engineer's
   talking: turn **Voice on** there and off on the PC.

### Record and replay a session

1. Before you go out, press **● Record** on the Live page (or turn on automatic recording in Settings).
2. Drive. The button shows how long and how big the recording is.
3. Later, open the session and click **▶ Replay**, or use **Settings → Recordings**.
4. Use the speed buttons and the slider to jump to the moment you want; the whole Live page, engineer
   included, plays it back.

### Back up or move your history

1. Close the app.
2. Copy the data folder: on Windows the `data` folder next to the exe, on a Mac
   `~/Library/Application Support/F1 Telemetry Hub`. **Settings → Data → Open data folder** opens it.
3. To move to another Windows PC, put the exe and the copied `data` folder side by side there. To move to a
   Mac (or from one), put the folder's contents where that computer keeps them; the files are the same on
   both.

## What the numbers mean

| Term | Meaning |
|---|---|
| Delta | The time difference to a reference lap at the same point of the lap. **−0.250** means a quarter of a second ahead |
| Micro-sectors | Every sector split into 8 equal parts, 24 per lap, timed live. **Purple:** your record for that stretch (best ever on a valid lap at this circuit, same kind of session and car generation). **Green:** at least as quick as your personal-best lap there. **Yellow:** slower. Parts not reached yet show the last lap, faded |
| Ideal lap | Your micro-sector records added up: the lap you would do if you put your best of every stretch together |
| Typical lap | The median of a session's clean laps: half your laps are quicker, half slower. Coaching against it targets what you do on most laps, not one mistake |
| Best of every corner | Your best time through every corner in a session, added to the rest of your best lap |
| Consistency | The spread (standard deviation) of your clean lap times. Under 0.2 s is very consistent |
| Understeer angle | How much more the front tyres slide sideways than the rears (from the game's Motion Ex data). Above zero the car understeers (pushes wide), below zero it oversteers (the rear steps out). Around 0.5° is noticeable, 1.2° and more is a lot |
| Wheelspin / lock-up | The rear wheels turning faster than the car is moving (wheelspin) or the wheels turning much slower under braking (lock-up), from the game's slip data |
| Drop-off | Seconds lost per lap for every lap the tyres get older. 0.05 s means lap 20 on a set is about 1 s slower than lap 1, fuel aside |
| Pit stop cost (pit loss) | The time a stop costs against staying out: the slower in-lap and out-lap, the pit lane and the stop itself |
| Tyre life | How many laps a compound lasts before the grip falls away, from the game's data and your measured wear (the app treats 70 % on the most worn tyre as the end) |

## Troubleshooting

### The pill says "Waiting for game"

- In the game, check **UDP Telemetry** is On, the **port** matches the one the app shows, and **UDP
  Broadcast Mode** is Off.
- Same PC: the IP address must be `127.0.0.1`. Console or another PC: it must be this PC's address, and
  the app must be allowed through Windows Firewall on **Private networks**. Check that Windows treats your
  network as Private (Settings → Network & internet → your connection → Network profile type).
- Mac: the IP address must be the Mac's, as the app's window shows it. If the macOS firewall is on, check
  F1 Telemetry Hub is allowed under **System Settings → Network → Firewall → Options**.
- The game sends nothing in its menus: start a session and go on track.
- A VPN on the PC can get in the way of a console reaching it.

### "UDP port unavailable"

Another program (often another telemetry app) is already listening on that port. Close it, or set this
app's **UDP port** in Settings to another number (for example 20778), restart it, and set the same number in
the game. To use both apps, see [Other telemetry apps at the same time](#other-telemetry-apps-at-the-same-time).

### "Unexpected packet sizes"

The game's **UDP Format** doesn't match what the app sees. Use 2026 with the 2026 Season Pack, otherwise 2025.
If a game update changed the packets, the app's next version will follow.

### The exe is blocked or deleted by antivirus

Single-file Python apps are sometimes flagged by antivirus programs because of how they unpack themselves.
If yours removes the exe, restore it from quarantine and add an exception for the app's folder. You can also
build the exe yourself from the source code (see the README).

### macOS says the app can't be opened, or is damaged

- *Could not verify … free of malware*: open **System Settings → Privacy & Security** and click
  **Open Anyway** next to the message about F1 Telemetry Hub (see [First start on a Mac](#first-start-on-a-mac)).
  The button stays there for about an hour after you try to open the app.
- *Is damaged and can't be opened*: usually the download was interrupted, so download the `.dmg` again. If it
  keeps happening, open **Terminal** and run
  `xattr -dr com.apple.quarantine "/Applications/F1 Telemetry Hub.app"`, then open the app again. That
  tells macOS you trust this download; only do it with a copy you downloaded from the project's GitHub page.

### The app closes straight away

- **Windows:** start the exe from a Command Prompt to read the message, or look for a second copy already
  running: the second start opens the first one's dashboard and closes after a few seconds.
- **Mac:** the app shows what went wrong in a message before it closes, and writes the details to `app.log`
  in its data folder.

If the dashboard port is taken by another program, the app tries the next nine ports.

### Forward UDP to doesn't reach the other device on a Mac

macOS asks before an app sends to other devices on your network. Turn F1 Telemetry Hub on under
**System Settings → Privacy & Security → Local Network**. Forwarding to `127.0.0.1` (an app on the same
Mac) doesn't need it.

### The dashboard doesn't open

Open `http://localhost:8777` yourself (the console window, or the app's window on a Mac, shows the exact
address; the Mac window's **Open dashboard** button opens it). If **Open the
dashboard when the app starts** is off in Settings, the app doesn't open it.

### The track map looks off, or says "Approximate positions"

At the start of a session, cars are placed by lap distance until you have driven a few corners; then the map
lines itself up with the game. That alignment is stored, so the next session at that circuit is right from
the first metre. Short layouts and a few circuits have no bundled outline: their map appears after your first
lap.

### No setup, tyre or damage data in online sessions

Set **Your Telemetry** to **Public** in the game's telemetry settings. Other drivers' data depends on
theirs.

### The voice is silent

Click once anywhere on the Live page (browsers keep pages silent until you do), check **Voice on**, and check
the kinds you want are ticked under **Messages**. On a phone, also check the ringer and media volume.

### The phone can't open the dashboard

Turn on **Allow LAN access** and restart the app, allow it through the firewall on Private networks, and make
sure the phone is on the same Wi-Fi (not a guest network, not mobile data).

### The strategy helper says "The strategy helper works in races"

It only plans races with a set number of laps. On intermediates or wets it stands back: the weather decides
the stops.

### The coach says "Not enough to go on"

It needs at least two complete flying laps with telemetry in the session, within 107 % of the best.

### The setup advisor says "not enough data"

It needs cornering samples with balance data at each speed: drive four or more laps with that setup. Balance
data comes from the game's Motion Ex packet, sent with UDP Format 2024 or newer.

## Your data

- Everything stays on your computer: a SQLite database (`f1telemetry.db`), your settings (`settings.json`)
  and recordings (the `recordings` folder). **Settings → Data** shows where and how big it is.
  - **Windows:** in the `data` folder next to the exe.
  - **Mac:** in `~/Library/Application Support/F1 Telemetry Hub`, with `app.log`, the messages a console
    window would show.
- Nothing is sent anywhere, apart from the UDP packets you choose to forward to other apps.
- Exported lap files contain your in-game name, the lap's telemetry and the setup you used. Recordings
  contain everything the game sent, including other drivers' names in online sessions.
- To start afresh, close the app and delete (or rename) the `data` folder.

## Command line

The app takes a few options, for a shortcut or a script:

```
F1TelemetryHub.exe [--udp-port 20777] [--http-port 8777] [--data-dir PATH] [--no-browser]
                   [--demo race|quali|tt|weekend] [--demo-format 2025|2026] [--demo-laps N] [--demo-speed X]
```

On a Mac, run the program inside the app from Terminal, with the same options:
`"/Applications/F1 Telemetry Hub.app/Contents/MacOS/F1TelemetryHub"`. Add `--no-window` to run it in the
terminal without the app's window (stop it with Ctrl+C).

`--udp-port` and `--http-port` apply to that run only (Settings stores permanent changes). `--data-dir`, or
the `F1TH_DATA_DIR` environment variable, keeps the history somewhere else, for example in a synced folder.
`--demo` starts the demo straight away.

"""Lookup tables from the EA F1 25 UDP specification appendices (formats 2025 and 2026)."""

PACKET_NAMES = {
    0: "Motion",
    1: "Session",
    2: "Lap Data",
    3: "Event",
    4: "Participants",
    5: "Car Setups",
    6: "Car Telemetry",
    7: "Car Status",
    8: "Final Classification",
    9: "Lobby Info",
    10: "Car Damage",
    11: "Session History",
    12: "Tyre Sets",
    13: "Motion Ex",
    14: "Time Trial",
    15: "Lap Positions",
    16: "Car Telemetry 2",
}

TRACKS = {
    0: "Melbourne",
    1: "Paul Ricard",
    2: "Shanghai",
    3: "Sakhir (Bahrain)",
    4: "Catalunya",
    5: "Monaco",
    6: "Montreal",
    7: "Silverstone",
    8: "Hockenheim",
    9: "Hungaroring",
    10: "Spa",
    11: "Monza",
    12: "Singapore",
    13: "Suzuka",
    14: "Abu Dhabi",
    15: "Texas (COTA)",
    16: "Brazil (Interlagos)",
    17: "Austria",
    18: "Sochi",
    19: "Mexico",
    20: "Baku",
    21: "Sakhir Short",
    22: "Silverstone Short",
    23: "Texas Short",
    24: "Suzuka Short",
    25: "Hanoi",
    26: "Zandvoort",
    27: "Imola",
    28: "Portimao",
    29: "Jeddah",
    30: "Miami",
    31: "Las Vegas",
    32: "Losail (Qatar)",
    39: "Silverstone (Reverse)",
    40: "Austria (Reverse)",
    41: "Zandvoort (Reverse)",
    42: "Madrid",
    99: "Demo Circuit",
}

SESSION_TYPES = {
    0: "Unknown",
    1: "Practice 1",
    2: "Practice 2",
    3: "Practice 3",
    4: "Short Practice",
    5: "Qualifying 1",
    6: "Qualifying 2",
    7: "Qualifying 3",
    8: "Short Qualifying",
    9: "One-Shot Qualifying",
    10: "Sprint Shootout 1",
    11: "Sprint Shootout 2",
    12: "Sprint Shootout 3",
    13: "Short Sprint Shootout",
    14: "One-Shot Sprint Shootout",
    15: "Race",
    16: "Race 2",
    17: "Race 3",
    18: "Time Trial",
}


def session_category(session_type: int) -> str:
    if session_type in (1, 2, 3, 4):
        return "practice"
    if 5 <= session_type <= 14:
        return "qualifying"
    if session_type in (15, 16, 17):
        return "race"
    if session_type == 18:
        return "time_trial"
    return "other"


TEAMS = {
    0: "Mercedes",
    1: "Ferrari",
    2: "Red Bull Racing",
    3: "Williams",
    4: "Aston Martin",
    5: "Alpine",
    6: "RB",
    7: "Haas",
    8: "McLaren",
    9: "Sauber",
    41: "F1 Generic",
    104: "F1 Custom Team",
    129: "Konnersport",
    142: "APXGP '24",
    154: "APXGP '25",
    155: "Konnersport '24",
    158: "Art GP '24",
    159: "Campos '24",
    160: "Rodin Motorsport '24",
    161: "AIX Racing '24",
    162: "DAMS '24",
    163: "Hitech '24",
    164: "MP Motorsport '24",
    165: "Prema '24",
    166: "Trident '24",
    167: "Van Amersfoort Racing '24",
    168: "Invicta '24",
    185: "Mercedes '24",
    186: "Ferrari '24",
    187: "Red Bull Racing '24",
    188: "Williams '24",
    189: "Aston Martin '24",
    190: "Alpine '24",
    191: "RB '24",
    192: "Haas '24",
    193: "McLaren '24",
    194: "Sauber '24",
    465: "Art GP '25",
    466: "Campos '25",
    467: "Rodin Motorsport '25",
    468: "AIX Racing '25",
    469: "DAMS '25",
    470: "Hitech '25",
    471: "MP Motorsport '25",
    472: "Prema '25",
    473: "Trident '25",
    474: "Van Amersfoort Racing '25",
    475: "Invicta '25",
    476: "Mercedes '26",
    477: "Ferrari '26",
    478: "Red Bull Racing '26",
    479: "Williams '26",
    480: "Aston Martin '26",
    481: "Alpine '26",
    482: "RB '26",
    483: "Haas '26",
    484: "McLaren '26",
    485: "Audi '26",
    486: "Cadillac '26",
    489: "Art GP '26",
    490: "Campos '26",
    491: "Rodin Motorsport '26",
    492: "AIX Racing '26",
    493: "DAMS '26",
    494: "Hitech '26",
    495: "MP Motorsport '26",
    496: "Prema '26",
    497: "Trident '26",
    498: "Van Amersfoort Racing '26",
    499: "Invicta '26",
}

# Broadcast-style team colours, used only for small identity chips next to names.
TEAM_COLOURS = {
    0: "#27F4D2",
    1: "#E8002D",
    2: "#3671C6",
    3: "#64C4FF",
    4: "#229971",
    5: "#FF87BC",
    6: "#6692FF",
    7: "#B6BABD",
    8: "#FF8000",
    9: "#52E252",
    485: "#BB0A30",  # Audi '26
    486: "#B4975A",  # Cadillac '26
}
# the 2026 cars of the existing teams (476-484) keep their team's colour
TEAM_COLOURS.update({476 + i: TEAM_COLOURS[t] for i, t in enumerate((0, 1, 2, 3, 4, 5, 6, 7, 8))})

ACTUAL_COMPOUNDS = {
    16: "C5", 17: "C4", 18: "C3", 19: "C2", 20: "C1", 21: "C0", 22: "C6",
    7: "Inter", 8: "Wet",
    9: "Dry", 10: "Wet",
    11: "Super Soft", 12: "Soft", 13: "Medium", 14: "Hard", 15: "Wet",
}

VISUAL_COMPOUNDS = {
    16: "Soft", 17: "Medium", 18: "Hard", 7: "Inter", 8: "Wet",
    15: "Wet", 19: "Super Soft", 20: "Soft", 21: "Medium", 22: "Hard",
}

WEATHER = {0: "Clear", 1: "Light Cloud", 2: "Overcast", 3: "Light Rain", 4: "Heavy Rain", 5: "Storm"}

SAFETY_CAR = {0: "None", 1: "Safety Car", 2: "Virtual SC", 3: "Formation Lap"}

FUEL_MIX = {0: "Lean", 1: "Standard", 2: "Rich", 3: "Max"}

ERS_MODES = {0: "None", 1: "Medium", 2: "Hotlap", 3: "Overtake"}

PIT_STATUS = {0: "", 1: "Pitting", 2: "In Pit"}

DRIVER_STATUS = {0: "Garage", 1: "Flying Lap", 2: "In Lap", 3: "Out Lap", 4: "On Track"}

RESULT_STATUS = {
    0: "Invalid", 1: "Inactive", 2: "Active", 3: "Finished",
    4: "DNF", 5: "DSQ", 6: "Not Classified", 7: "Retired",
}

FORMULA = {0: "F1 Modern", 1: "F1 Classic", 2: "F2", 3: "F1 Generic", 4: "Beta",
           6: "Esports", 8: "F1 World", 9: "F1 Elimination", 13: "F1 26"}

GAME_MODES = {
    0: "Event Mode", 3: "Grand Prix", 4: "Grand Prix '23", 5: "Time Trial", 6: "Splitscreen",
    7: "Online Custom", 8: "Online League", 11: "Career Invitational", 12: "Championship Invitational",
    13: "Championship", 14: "Online Championship", 15: "Online Weekly Event",
    17: "Story Mode (Braking Point)", 19: "Career '22", 20: "Career '22 Online", 21: "Career '23",
    22: "Career '23 Online", 23: "Driver Career '24", 24: "Career '24 Online", 25: "My Team Career '24",
    26: "Curated Career '24", 27: "My Team Career '25", 28: "Driver Career '25", 29: "Career '25 Online",
    30: "Challenge Career '25", 75: "Story Mode (APXGP)", 127: "Benchmark",
}
CAREER_MODES = {19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30}
MY_TEAM_MODES = {25, 27}
CHAMPIONSHIP_MODES = {8, 11, 12, 13, 14}
ONLINE_MODES = {7, 8, 14, 15, 20, 22, 24, 29}

TT_GEARBOX = {1: "Manual", 2: "Manual + suggested", 3: "Automatic"}
TT_TRACTION = {0: "Off", 1: "Medium", 2: "Full"}


def mode_group(game_mode) -> str:
    """Coarse grouping used for filters: career, championship, time_trial, grand_prix, online, other."""
    if game_mode in CAREER_MODES:
        return "career"
    if game_mode in CHAMPIONSHIP_MODES:
        return "championship"
    if game_mode == 5:
        return "time_trial"
    if game_mode in (3, 4):
        return "grand_prix"
    if game_mode in ONLINE_MODES:
        return "online"
    return "other"


MODE_GROUPS = ("career", "championship", "time_trial", "grand_prix", "online", "other")

EVENT_NAMES = {
    "SSTA": "Session Started",
    "SEND": "Session Ended",
    "FTLP": "Fastest Lap",
    "RTMT": "Retirement",
    "DRSE": "DRS Enabled",
    "DRSD": "DRS Disabled",
    "TMPT": "Team Mate In Pits",
    "CHQF": "Chequered Flag",
    "RCWN": "Race Winner",
    "PENA": "Penalty",
    "SPTP": "Speed Trap",
    "STLG": "Start Lights",
    "LGOT": "Lights Out",
    "DTSV": "Drive Through Served",
    "SGSV": "Stop Go Served",
    "FLBK": "Flashback",
    "BUTN": "Button",
    "RDFL": "Red Flag",
    "OVTK": "Overtake",
    "SCAR": "Safety Car",
    "COLL": "Collision",
    "PMEN": "Partial Mode Enabled",
    "PMDI": "Partial Mode Disabled",
    "OVEN": "Overtake Mode Enabled",
    "OVDI": "Overtake Mode Disabled",
}

COLLISION_SEVERITY = {0: "low", 1: "medium", 2: "high"}
PARTIAL_MODE_REASONS = {0: "wet track", 1: "safety car", 2: "red flag"}

PENALTY_TYPES = {
    0: "Drive through", 1: "Stop Go", 2: "Grid penalty", 3: "Penalty reminder",
    4: "Time penalty", 5: "Warning", 6: "Disqualified", 7: "Removed from formation lap",
    8: "Parked too long timer", 9: "Tyre regulations", 10: "This lap invalidated",
    11: "This and next lap invalidated", 12: "This lap invalidated without reason",
    13: "This and next lap invalidated without reason", 14: "This and previous lap invalidated",
    15: "This and previous lap invalidated without reason", 16: "Retired", 17: "Black flag timer",
}

INFRINGEMENT_TYPES = {
    0: "Blocking by slow driving", 1: "Blocking by wrong way driving",
    2: "Reversing off the start line", 3: "Big collision", 4: "Small collision",
    5: "Collision failed to hand back position single", 6: "Collision failed to hand back position multiple",
    7: "Corner cutting gained time", 8: "Corner cutting overtake single",
    9: "Corner cutting overtake multiple", 10: "Crossed pit exit lane", 11: "Ignoring blue flags",
    12: "Ignoring yellow flags", 13: "Ignoring drive through", 14: "Too many drive throughs",
    15: "Drive through reminder serve within n laps", 16: "Drive through reminder serve this lap",
    17: "Pit lane speeding", 18: "Parked for too long", 19: "Ignoring tyre regulations",
    20: "Too many penalties", 21: "Multiple warnings", 22: "Approaching disqualification",
    23: "Tyre regulations select single", 24: "Tyre regulations select multiple",
    25: "Lap invalidated corner cutting", 26: "Lap invalidated running wide",
    27: "Corner cutting ran wide gained time minor", 28: "Corner cutting ran wide gained time significant",
    29: "Corner cutting ran wide gained time extreme", 30: "Lap invalidated wall riding",
    31: "Lap invalidated flashback used", 32: "Lap invalidated reset to track",
    33: "Blocking the pitlane", 34: "Jump start", 35: "Safety car to car collision",
    36: "Safety car illegal overtake", 37: "Safety car exceeding allowed pace",
    38: "Virtual safety car exceeding allowed pace", 39: "Formation lap below allowed speed",
    40: "Formation lap parking", 41: "Retired mechanical failure", 42: "Retired terminally damaged",
    43: "Safety car falling too far back", 44: "Black flag timer", 45: "Unserved stop go penalty",
    46: "Unserved drive through penalty", 47: "Engine component change",
    48: "Gearbox change", 49: "Parc Fermé change", 50: "League grid penalty",
    51: "Retry penalty", 52: "Illegal time gain", 53: "Mandatory pitstop",
    54: "Attribute assigned",
}

SURFACE_TYPES = {
    0: "Tarmac", 1: "Rumble strip", 2: "Concrete", 3: "Rock", 4: "Gravel", 5: "Mud",
    6: "Sand", 7: "Grass", 8: "Water", 9: "Cobblestone", 10: "Metal", 11: "Ridged",
}

# Wheel arrays in every packet are ordered RL, RR, FL, FR.
WHEELS = ["RL", "RR", "FL", "FR"]


def name_or(table: dict, key, prefix: str = "") -> str:
    if key in table:
        return table[key]
    return f"{prefix}{key}" if prefix else str(key)

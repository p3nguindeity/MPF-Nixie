# MPF-Nixie
This integration connects Mission Pinball Framework (MPF) to EasyNixie-driven nixie tubes through an Arduino Nano. It allows MPF modes, logic, and events to control digits and LED colors on real nixie tubes just like any other display device.

EASYNIXIE: https://www.tindie.com/products/allexok/easynixie/

It provides:

Real-time tube updates (per-tube or multi-digit display)
Per-tube RGB LED color control
Attract mode handoff (Arduino shows random digits until MPF takes over)
Serial-based communication between MPF and Arduino
Native MPF color compatibility (names like “red”, “orange”, “#00ff88” work automatically)

1. MPF → nixie.py (Platform Layer)

nixie.py is a custom SegmentDisplayPlatform driver for MPF.
It registers new display devices (e.g., nixie_0, nixie_1, or nixie_score).
When MPF triggers a segment_display_player entry, it converts the text and color into a serial command.
Command format: N,<index>,<digit>,<R>,<G>,<B>,<dim>\n

Field	Description:

index	Tube number (0–5 for 6 tubes)
digit	Value 0–9 (10 = blank)
R,G,B	Color brightness values (0–255)
dim	Brightness / PWM (0 = full on, 255 = off)

Examples:

N,2,5,255,0,0,0       → Tube 2 shows "5" in red
N,5,9,0,255,255,10    → Tube 5 shows "9" in cyan, slightly dimmed


2. Arduino Firmware (nixie.ino)

Listens for serial input at 9600 baud.
Parses incoming commands line-by-line.
Converts each R,G,B into the nearest EasyNixie LED color enum.
Updates the nixie chain (farthest → nearest) using SetNixie() and Latch().

| Command | Description                                             |
| ------- | ------------------------------------------------------- |
| `N,...` | Normal display update                                   |
| `A`     | Re-enters local attract mode (random digits)            |
| `42`    | Debug: responds `"so long and thanks for all the fish"` |

Attract Mode:

When no commands have been received:
Each tube cycles random digits (0–9) every 50 ms.
All LEDs glow red.
When MPF sends its first command, attract stops automatically.

3. MPF Configuration (config.yaml)

nixie:
  port: COM6                # Serial port to Arduino
  baud: 9600
  default_color: [255, 0, 0]
  default_dim: 0
  auto_attract: "A"         # Send "A" when attract starts / game ends
  ignore_updates_in_attract: true
  debug: false

This tells MPF to:

Open the serial port when the game starts,
Send A\n to trigger Arduino attract mode,
Ignore MPF display updates while attract is active,
Translate MPF color names into RGB (via mpf.core.rgb_color.RGBColor).

4. Per-Tube Control

Each nixie can be individually addressed:

segment_display_player:
  score_hit:
    nixie_0: { text: "1", color: "red" }
    nixie_1: { text: "2", color: "orange" }
    nixie_2: { text: "3", color: "yellow" }
    nixie_3: { text: "4", color: "green" }
    nixie_4: { text: "5", color: "blue" }
    nixie_5: { text: "6", color: "purple" }

Or you can define one 6-tube display:

segment_displays:
  nixie_score:
    number: 0
    size: 6
    platform: nixie

segment_display_player:
  update_score:
    nixie_score:
      text: "123456"
      colors: ["red", "orange", "yellow", "green", "blue", "purple"]

Arduino Pinout:

| Arduino Pin | EasyNixie Pin | Function                   |
| ----------- | ------------- | -------------------------- |
| D4          | SHCP          | Shift Clock                |
| D2          | STCP          | Storage Clock (Latch)      |
| D5          | DSIN          | Serial Data In             |
| D3          | OUT_EN        | Output Enable (active low) |
| 5V          | VCC           | Power                      |
| GND         | GND           | Ground                     |

Serial Protocol Summary:

| Command                 | Description     |
| ----------------------- | --------------- |
| `N,idx,digit,r,g,b,dim` | Update one tube |
| `A`                     | Resume attract  |
| `42`                    | Debug/test      |
| (Any other)             | Ignored         |

Deployment:

Copy nixie folder into mpf platforms folder

add the below entry to config_spec.yaml

nixie:
    __valid_in__: machine
    __type__: config
    port: single|str|
    baud: single|int|115200
    debug: single|bool|false
    console_log: single|enum(none,basic,full)|basic
    file_log: single|enum(none,basic,full)|basic

Add the below entry to mpfconfig.yaml under the platforms section

nixie: mpf.platforms.nixie.nixie.NixiePlatform






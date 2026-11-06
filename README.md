# From Bin to Menu — Food Waste Camera (AI Job 1 · SEE)

Opens the Mac camera. When a new object is placed in front of it and held still for a moment (0.6 s), a photo is taken automatically and sent to Claude:
- **Food** → each item is listed with an estimated weight (g) and energy (kcal)
- **Not food** → the result is marked "NOT FOOD" and lists the objects Claude detected

Food is recognised wherever it appears — on a tray, in a bin, held in a hand, packaged, or as a picture of food on a phone or screen.

Layout: the live camera view on the left, a strip of photo icons below it where each new photo slides in from the right (swipe or drag the strip to look back at older photos; click an icon for the full photo and details), and a detection log with date, time and response time on the right. Drag the divider between them to resize the log; A− / A+ (or ⌘− / ⌘+) change the log text size.

**Privacy:** faces are detected on-device with Apple's Vision framework and blurred in the live view, in saved photos, and before any image is sent to Claude.

**Architecture:** see [docs/arc42.md](docs/arc42.md) — goals, constraints, building blocks, runtime, deployment, decisions, quality scenarios and risks, in the arc42 template.

## Screenshot

![From Bin to Menu running with five sample photos](docs/images/screenshot.jpg)

The app analysing five sample photos with **Claude Haiku 4.5** (the default model). The results below are the responses shown in the screenshot. For this run, a temporary test harness (not part of the app) passed each sample photo to the app in place of a camera frame, 1–2 s apart. That is why the timestamps in the screenshot are closer together than the 3 s minimum between automatic captures. The app itself only reads from a camera, so you cannot reproduce this run without writing a similar harness (see [arc42 §11, D-2](docs/arc42.md#11-risks-and-technical-debt)).

| # | Sample photo | Result | Estimated total | Response | Cost |
|---|---|---|---|---|---|
| 1 | <img src="docs/images/nonfood_stapler.jpg" width="120"> | 🚫 **NOT FOOD** — a stapler | — | 2.6 s | US$0.0024 |
| 2 | <img src="docs/images/waste_vegetables.jpg" width="120"> | 🍱 Food — oranges, apples, pears, eggplants and more (8 items) | 6,700 g · 2,895 kcal | 5.9 s | US$0.0040 |
| 3 | <img src="docs/images/waste_pizza.jpg" width="120"> | 🍱 Food — sheet pizza | 1,200 g · 3,200 kcal | 3.8 s | US$0.0031 |
| 4 | <img src="docs/images/tray_finland.jpg" width="120"> | 🍱 Food — meat and vegetable stew, bread, cucumber, milk | 915 g · 785 kcal | 6.3 s | US$0.0039 |
| 5 | <img src="docs/images/tray_usda.jpg" width="120"> | 🍱 Food (picture of food) — sandwich, fruit salad, bean soup, milk | 800 g · 650 kcal | 5.3 s | US$0.0034 |

These are Claude's visual estimates, not measurements, and they have not been checked against a scale. Photo 2, for example, is a heap of produce whose weight is hard to judge from one angle.

Photo 5 is a misclassification: it is a photograph of a real tray, but Claude labelled it a *picture of food*. The real-versus-picture label (`food_source`) is not reliable yet (see [arc42 §11, R-2](docs/arc42.md#11-risks-and-technical-debt)).

## Install and run
```bash
pip3 install -r requirements.txt
python3 bin_to_menu.py
```
**API key:** create one at [platform.claude.com](https://platform.claude.com) (Settings → API Keys), then put it in a `.env` file next to `bin_to_menu.py` (this file is git-ignored):
```
ANTHROPIC_API_KEY=sk-ant-...
# Only needed if your key is not scoped to a workspace (Settings → Workspaces):
ANTHROPIC_WORKSPACE_ID=wrkspc_...
# Optional: add another model to the dropdown and make it the default
# BINTOMENU_MODEL=claude-...
```
Alternatively, `export ANTHROPIC_API_KEY=sk-ant-...` in the terminal before starting.
On first launch macOS asks for camera permission. If it doesn't, allow Terminal (or VS Code) under System Settings → Privacy & Security → Camera.

Options: `--camera 1` uses another camera (e.g. iPhone Continuity Camera); `--no-save` does not store photos (privacy mode; the JSON log is still written).
Model: choose in the **Model** dropdown — *Fast · Haiku 4.5* (default — cheapest and fastest), *Balanced · Sonnet 5*, *Accurate · Opus 5* (slowest, most expensive). The log shows the response time of every request.

Keys: S = start / stop camera (▶ Start / ■ Stop button) | Space = manual capture | R = reset background | A = toggle auto-detect | Q / Esc = quit

## Cost display
The log panel shows **This session** — the exact cost of every request so far, calculated from the token counts Claude returns. With Haiku 4.5 the sample photos cost US$0.0024–0.0040 each; photos with more food items cost more, because the answer is longer. Each log entry also shows its own cost. Anthropic has no API for reading the remaining credit balance; check it in the Console (Settings → Billing).

## Output
- `captures/` — captured photos (faces already blurred)
- `logs/detections.jsonl` — one record per detection (time, foods, grams, kcal, tokens, cost). Ids restart at 1 on every launch, so use the timestamp together with the id.

## Tips
- Start with the camera looking at an empty scene (a table or tray area); the program uses it as the background. Press R whenever the background changes.
- Each object is analysed once; remove it or add a new item to trigger another capture. Automatic captures are at least 3 s apart, and head movements are ignored, so sitting in front of the camera does not trigger captures. Space captures at any time.
- Grams and kcal are Claude's visual **estimates**, not measurements. Calibrating them against a kitchen scale is planned for Weeks 1–3 (deck slide 7).

## Documentation
| Document | Content |
|---|---|
| [README.md](README.md) | What the app does, how to install and use it |
| [docs/arc42.md](docs/arc42.md) | Architecture documentation (arc42 template, sections 1–12) |
| [CLAUDE.md](CLAUDE.md) | Notes for Claude Code: project layout, commands, documentation rules |
| [.claude/skills/arc42-docs/SKILL.md](.claude/skills/arc42-docs/SKILL.md) | Claude Code skill for keeping the documentation in line with arc42 and the code |

## Image credits

Sample photos from Wikimedia Commons. Four were resized to 1280 px wide; the stapler photo is 640 × 480. Camera metadata (EXIF) was removed from all of them.

| File | Source | Author | License |
|---|---|---|---|
| `docs/images/tray_usda.jpg` | [School lunch tray MyPlate 20210810-FNS-UNC-0015.jpg](https://commons.wikimedia.org/wiki/File:School_lunch_tray_MyPlate_20210810-FNS-UNC-0015.jpg) | U.S. Department of Agriculture | Public domain |
| `docs/images/tray_finland.jpg` | [School lunch in ylästö school.jpg](https://commons.wikimedia.org/wiki/File:School_lunch_in_yl%C3%A4st%C3%B6_school.jpg) | Jukajuha | CC0 |
| `docs/images/waste_pizza.jpg` | [Pizza with food waste.jpg](https://commons.wikimedia.org/wiki/File:Pizza_with_food_waste.jpg) | PizzaToast | CC0 |
| `docs/images/waste_vegetables.jpg` | [Vegetables from a food retailer's container.jpg](https://commons.wikimedia.org/wiki/File:Vegetables_from_a_food_retailer%27s_container.jpg) | PizzaToast | CC0 |
| `docs/images/nonfood_stapler.jpg` | [Stapler "Delfin" 1.jpg](https://commons.wikimedia.org/wiki/File:Stapler_%22Delfin%22_1.jpg) | OFFset32 at Polish Wikipedia | Public domain |

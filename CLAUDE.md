# CLAUDE.md

Notes for Claude Code working in this repository.

## Project

From Bin to Menu — Food Waste Camera ("AI Job 1 · SEE"). A macOS desktop app in Python that watches a camera, captures a photo when a new object is held still, blurs faces on the device, and asks Claude to list the foods with estimated grams and kcal (or say what it sees if it is not food).

## Layout

| Path | Content |
|---|---|
| `bin_to_menu.py` | The whole app: settings and prompt at the top, then `FaceBlurrer`, `FoodRecognizer`, `SceneTrigger`, `Detection`, `App` (Tkinter GUI), `main` |
| `requirements.txt` | pip dependencies (`opencv-python<5`; `pyobjc-framework-Vision` on macOS only) |
| `README.md` | User guide: features, install, keys, cost, output, sample results, image credits |
| `docs/arc42.md` | Architecture documentation in the arc42 template (sections 1–12) |
| `docs/images/` | README screenshot and sample photos (Wikimedia Commons, EXIF removed) |
| `.claude/skills/arc42-docs/` | Skill for updating the documentation |
| `captures/`, `logs/`, `.env` | Created at run time; git-ignored, never commit them |

## Commands

```bash
pip3 install -r requirements.txt
python3 bin_to_menu.py              # needs ANTHROPIC_API_KEY (shell or .env) and a camera
python3 -m py_compile bin_to_menu.py   # quick syntax check; works without a camera
```

There are no automated tests yet. The app needs a real camera and macOS for Apple Vision, so in a cloud or Linux session only the syntax check is possible. Say so instead of claiming the app was run.

## Code conventions

- Keep the single-file structure and the section banners (`# ───── Name ─────`).
- Tunable values are module constants at the top, with a short comment on each.
- Widgets are only touched on the Tk main thread. Worker threads only call the API and put results on `results_q`.
- Every frame that is shown, saved or sent must go through `FaceBlurrer.blur` when blurring is on. Never send or save the raw frame.
- `SYSTEM_PROMPT` and `RESULT_SCHEMA` change together. Then also update `_format_result`, `_append_jsonl` and arc42 §5.3.
- `MODEL_PRESETS` and `PRICES_PER_MTOK` change together. A new model family needs a branch in `FoodRecognizer.analyze`.
- Never log or print secret values; `load_dotenv` logs only names and lengths.

## Documentation rules (arc42)

Documentation follows the [arc42](https://arc42.org) template. When code changes, update the documents in the same commit:

| Change | Update |
|---|---|
| New or changed feature, key, option, output | `README.md` and arc42 §1.1 (requirements), §5 (building blocks) or §6 (runtime) |
| New dependency or platform requirement | `requirements.txt`, arc42 §2 (constraints) and §7 (deployment) |
| New design choice or trade-off | arc42 §9 (decisions), as a new `AD-n` row |
| New known risk, limitation or shortcut | arc42 §11, as a new `R-n` or `D-n` row; remove rows that were fixed |
| New term | arc42 §12 (glossary) |
| Threshold or timing constants (e.g. `STABLE_SECONDS`, `AUTO_COOLDOWN_S`) | Every place that quotes the number: README, arc42 §6.2, §10.2, §12 |

Rules for the content:
- The code is the source of truth. Check every number, name and behaviour against `bin_to_menu.py` before writing it down.
- Sample results, costs and timings in the README come from a real run. Do not invent or round them up; widen stated ranges when new samples fall outside them.
- Say "estimate" for grams and kcal; they are not calibrated (arc42 R-1).
- State each fact in one place and link to it, instead of repeating it with different wording.
- Strip EXIF metadata from images before committing them, and keep the credits table in the README accurate (size, source, author, licence).
- Documents are in English; write plainly, with short sentences and tables.

Use the `arc42-docs` skill for documentation work.

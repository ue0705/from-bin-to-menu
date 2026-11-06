---
name: arc42-docs
description: Update or review this repository's documentation (README.md, docs/arc42.md, CLAUDE.md) so it follows the arc42 template and matches bin_to_menu.py. Use after code changes, when asked to write, fix or check documentation, or when a review finds a mismatch between the docs and the code.
---

# arc42 documentation for From Bin to Menu

The architecture documentation is `docs/arc42.md`, one file with the 12 arc42 sections. `README.md` is the user guide and links to it. `CLAUDE.md` holds the rules for keeping both up to date.

## Steps

1. **Find what changed.** Run `git diff` (or `git diff <base>...HEAD`) and list each change to behaviour, settings, dependencies, outputs or the UI in `bin_to_menu.py` and `requirements.txt`.
2. **Map each change to sections** with this table:

   | Kind of change | arc42 section | README section |
   |---|---|---|
   | Goal, requirement, stakeholder | 1 Introduction and Goals | intro |
   | Platform, library, licence or policy limit | 2 Constraints | Install and run |
   | New external system, input or output | 3 Context and Scope | Output |
   | Overall approach | 4 Solution Strategy | — |
   | Class, method, schema field | 5 Building Block View | — |
   | Sequence, trigger rule, error handling | 6 Runtime View | Tips |
   | Machine, file location, dependency | 7 Deployment View | Install and run, Output |
   | Privacy, config, threads, cost, persistence, UI rules | 8 Cross-cutting Concepts | Privacy, Cost display |
   | Design choice and its trade-off | 9 Architecture Decisions (`AD-n`) | — |
   | Measurable quality expectation | 10 Quality Requirements (`Q-n`) | — |
   | Known risk, limitation, shortcut | 11 Risks and Technical Debt (`R-n`, `D-n`) | short note + link |
   | New term | 12 Glossary | — |

3. **Check every fact against the code** before writing it: constant values (e.g. `STABLE_SECONDS`, `AUTO_COOLDOWN_S`, `SEND_MAX_SIDE`, thresholds), model ids and prices, CLI options, keys, file names, JSONL fields, log and result texts (quote `_format_result` output exactly).
4. **Check the numbers in the README** against their source: sample results come from a real run (screenshot); a stated range must include every sample; never invent values.
5. **Check images**: sizes and EXIF with PIL (`Image.open(p).size`, `'exif' in Image.open(p).info`). Strip EXIF before committing, keeping the ICC profile. Keep the credits table accurate.
6. **Remove duplication**: each fact lives in one place; elsewhere link to it (`docs/arc42.md#11-risks-and-technical-debt`).
7. **Update the tables of risks and debt**: add new items, delete items the change fixed, and keep ids stable (do not renumber existing rows).
8. **Verify** with `python3 -m py_compile bin_to_menu.py`, and check that every relative link in the changed documents points to an existing file.

## Style

- English, plain words, short sentences, tables for lists of facts.
- Mermaid for diagrams (GitHub renders it).
- Grams and kcal are always "estimates".
- Do not describe features that the code does not have; put wanted features in §11 as debt.

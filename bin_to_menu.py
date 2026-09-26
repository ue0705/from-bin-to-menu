#!/usr/bin/env python3
"""
From Bin to Menu — AI Job 1 · SEE
Live-camera food-waste recognition. When a new object enters the frame and holds
still, a photo is taken automatically and sent to Claude, which identifies the foods
and estimates their weight (g) and energy (kcal). If it is not food, Claude says
what it sees instead. Faces are blurred on screen, in saved photos and before
anything is sent to Claude.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...   (or put it in a .env file next to this script)
    python3 bin_to_menu.py            # built-in camera (index 0)
    python3 bin_to_menu.py --camera 1 # another camera (e.g. iPhone Continuity Camera)

Keys: Space = manual capture   R = reset background   A = toggle auto-detect   Q / Esc = quit
"""

import argparse
import base64
import json
import os
import queue
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
from PIL import Image, ImageDraw, ImageTk

import anthropic

# ───────────────────────── Settings ─────────────────────────
# Speed / accuracy presets shown in the model dropdown.
MODEL_PRESETS = {
    "Fast · Haiku 4.5": "claude-haiku-4-5",
    "Balanced · Sonnet 5": "claude-sonnet-5",
    "Accurate · Opus 5": "claude-opus-5",
}
DEFAULT_PRESET = "Fast · Haiku 4.5"   # cheapest and fastest; switch in the dropdown when accuracy matters more
if os.environ.get("BINTOMENU_MODEL"):
    MODEL_PRESETS = {f"Custom · {os.environ['BINTOMENU_MODEL']}": os.environ["BINTOMENU_MODEL"], **MODEL_PRESETS}
    DEFAULT_PRESET = next(iter(MODEL_PRESETS))

APP_DIR = Path(__file__).resolve().parent
CAPTURE_DIR = APP_DIR / "captures"
LOG_FILE = APP_DIR / "logs" / "detections.jsonl"

ICON_SIZE = 96                   # thumbnail icon size
ICON_GAP = 14
MARQUEE_SPEED = 1.2              # icon scroll speed (px / frame)
SEND_MAX_SIDE = 1024             # longest side of the image sent to Claude (1024×576 ≈ 790 image tokens)

# Auto-detection parameters
DETECT_W = 320                   # downscaled width used for detection
PIXEL_DIFF_TH = 28               # per-pixel difference threshold (0-255)
FG_RATIO_TH = 0.04               # > 4% of area differs from background = "object present"
MOTION_RATIO_TH = 0.02           # < 2% differs from previous frame = "still" (tolerates a hand-held item)
STABLE_SECONDS = 0.6             # how long the scene must stay still before capture
EMPTY_RATIO_TH = 0.015           # < 1.5% differs from background = "empty scene"
RECAPTURE_RATIO_TH = 0.05        # must differ > 5% from last capture (avoids re-analysing the same scene)
AUTO_COOLDOWN_S = 3.0            # minimum gap between two automatic captures
HEAD_MASK_PAD = 0.8              # ignore motion in each face box enlarged by 80% (head turns, nodding)

# Face blurring
FACE_DETECT_W = 640              # downscaled width used for face detection
FACE_HOLD_FRAMES = 8             # keep blurring a face box this many frames after it was last seen
FACE_PAD = 0.5                   # enlarge each face box by 50% on every side (hair, ears, chin)
FACE_BLOCKS = 7                  # pixelate each face to ~7 blocks across

# Colours
BG = "#0f1115"
PANEL = "#171a21"
FG = "#e6e6e6"
MUTED = "#8a8f98"
GREEN = "#3ecf8e"
RED = "#ff6b6b"
AMBER = "#f5b942"
BLUE = "#5aa9ff"

SYSTEM_PROMPT = """You are the food-waste analysis assistant for a school lunch programme
(AI Job 1 of the "From Bin to Menu" project). You receive one photo from a webcam.

Your job: find ANY food in the image and estimate how much there is.
- Food counts wherever it appears: on a tray, plate or bowl, in a bin, held in a hand, in packaging,
  or as a picture of food (a printed photo, a phone or laptop screen, a menu). Look at the whole frame,
  including small items near the edges.
- Food waste counts too: leftovers, half-eaten items, fruit peel, bones, soup residue.
- Name each item as specifically as you can (e.g. "stir-fried bok choy", not "vegetables").
- Estimate each item's weight in grams and energy in kcal, the way a dietitian eyeballs a plate.
  Judge size from reference objects (hands, plates, cutlery, the table, the screen). For a picture of
  food, estimate the portion that is shown as if it were real.
- Give a confidence level for each item (low / medium / high).
- total_grams and total_kcal are the sums over all items.
- food_source: "real" for physical food, "picture" for a photo or screen showing food,
  "packaged" for sealed or labelled products, "none" if there is no food.

If there is no food at all:
- Set is_food = false, items = [], totals = 0, food_source = "none".
- List the main objects you see in non_food_objects, and write one sentence in summary such as
  "Detected a computer mouse — this is not food."

Blurred regions are faces that were anonymised on purpose; ignore them. People, hands, furniture and
the background are not the subject unless nothing else is in the frame.
Write every text field in English. These are estimates, not measurements; note any uncertainty in notes."""

RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "is_food": {"type": "boolean"},
        "food_source": {"type": "string", "enum": ["real", "picture", "packaged", "none"]},
        "summary": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "estimated_grams": {"type": "number"},
                    "estimated_kcal": {"type": "number"},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                },
                "required": ["name", "estimated_grams", "estimated_kcal", "confidence"],
                "additionalProperties": False,
            },
        },
        "total_grams": {"type": "number"},
        "total_kcal": {"type": "number"},
        "non_food_objects": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "string"},
    },
    "required": ["is_food", "food_source", "summary", "items", "total_grams", "total_kcal",
                 "non_food_objects", "notes"],
    "additionalProperties": False,
}


def load_dotenv(path: Path = APP_DIR / ".env"):
    """Loads KEY=value lines from .env next to this script (without overriding real env vars)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.removeprefix("export ").strip()
        os.environ.setdefault(name, value.strip().strip('"').strip("'"))


load_dotenv()


def has_credentials() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


# ───────────────────────── Face detection & blurring ─────────────────────────
try:
    # Apple Vision (on-device, same detector as Photos) — far more reliable than Haar cascades,
    # handles glasses, tilted and partly turned faces.
    import Vision
    from Foundation import NSData
except ImportError:
    Vision = None


def _make_oval_mask(size=64):
    m = np.zeros((size, size), np.float32)
    cv2.ellipse(m, (size // 2, size // 2), (int(size * 0.42), int(size * 0.45)), 0, 0, 360, 1.0, -1)
    return cv2.GaussianBlur(m, (0, 0), size / 14)


OVAL_MASK = _make_oval_mask()


def _iou(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    iw = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    ih = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = iw * ih
    return inter / float(aw * ah + bw * bh - inter or 1)


class FaceBlurrer:
    """Finds faces with Apple Vision (fallback: OpenCV Haar cascades) and blurs them."""

    def __init__(self):
        self.backend = "Apple Vision" if Vision is not None else "OpenCV Haar"
        if Vision is not None:
            self.vn_request = Vision.VNDetectFaceRectanglesRequest.alloc().init()
        root = cv2.data.haarcascades
        self.frontal = cv2.CascadeClassifier(root + "haarcascade_frontalface_default.xml")
        self.profile = cv2.CascadeClassifier(root + "haarcascade_profileface.xml")
        self.tracks = []          # [x, y, w, h, frames_left] in full-frame coordinates
        self.frame_no = 0

    def _detect(self, frame):
        if Vision is not None:
            try:
                return self._detect_vision(frame)
            except Exception:  # noqa: BLE001 — fall back to Haar for this frame
                pass
        return self._detect_haar(frame)

    def _detect_vision(self, frame):
        h, w = frame.shape[:2]
        small = cv2.resize(frame, (FACE_DETECT_W, int(h * FACE_DETECT_W / w)))
        ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 80])
        data = NSData.dataWithBytes_length_(buf.tobytes(), len(buf))
        handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, None)
        handler.performRequests_error_([self.vn_request], None)
        boxes = []
        for face in self.vn_request.results() or []:
            bb = face.boundingBox()   # normalised, origin at bottom-left
            bx, by, bw, bh = bb.origin.x, bb.origin.y, bb.size.width, bb.size.height
            boxes.append((int(bx * w), int((1 - by - bh) * h), int(bw * w), int(bh * h)))
        return boxes

    def _detect_haar(self, frame):
        h, w = frame.shape[:2]
        scale = FACE_DETECT_W / w
        gray = cv2.cvtColor(cv2.resize(frame, (FACE_DETECT_W, int(h * scale))), cv2.COLOR_BGR2GRAY)
        opts = dict(scaleFactor=1.1, minNeighbors=3, minSize=(20, 20))
        # Alternate detectors between frames to keep the video smooth.
        if self.frame_no % 2 == 0:
            boxes = list(self.frontal.detectMultiScale(gray, **opts))
        else:
            boxes = list(self.profile.detectMultiScale(gray, **opts))
            gw = gray.shape[1]
            for (x, y, bw, bh) in self.profile.detectMultiScale(cv2.flip(gray, 1), **opts):
                boxes.append((gw - x - bw, y, bw, bh))
        return [(int(x / scale), int(y / scale), int(bw / scale), int(bh / scale)) for (x, y, bw, bh) in boxes]

    def update(self, frame):
        self.frame_no += 1
        self.tracks = [[*t[:4], t[4] - 1] for t in self.tracks if t[4] > 1]
        for box in self._detect(frame):
            # A new detection replaces any overlapping track, so boxes don't pile up.
            self.tracks = [t for t in self.tracks if _iou(t[:4], box) < 0.2]
            self.tracks.append([*box, FACE_HOLD_FRAMES])

    @property
    def boxes(self):
        return [tuple(t[:4]) for t in self.tracks]

    def blur(self, frame):
        """Returns a copy of the frame with every tracked face blurred."""
        out = frame.copy()
        fh, fw = out.shape[:2]
        for (x, y, w, h) in self.boxes:
            px, py = int(w * FACE_PAD), int(h * FACE_PAD)
            x0, y0 = max(0, x - px), max(0, y - py)
            x1, y1 = min(fw, x + w + px), min(fh, y + h + py)
            roi = out[y0:y1, x0:x1]
            if roi.size == 0:
                continue
            # Pixelate, then smooth: unrecognisable but still reads as "a face was here".
            rw, rh = x1 - x0, y1 - y0
            # Pixelate to ~FACE_BLOCKS blocks, then upscale smoothly: same strength at any face size.
            small = cv2.resize(roi, (FACE_BLOCKS, max(1, round(FACE_BLOCKS * rh / rw))), interpolation=cv2.INTER_AREA)
            blurred = cv2.resize(small, (rw, rh), interpolation=cv2.INTER_LINEAR)
            # Feathered oval (built small, then upscaled) so the area follows the head shape.
            mask = cv2.resize(OVAL_MASK, (rw, rh), interpolation=cv2.INTER_LINEAR)[..., None]
            roi[:] = (blurred * mask + roi * (1 - mask)).astype(np.uint8)
        return out


# ───────────────────────── Claude recognition ─────────────────────────
class FoodRecognizer:
    def __init__(self):
        # Keys that aren't scoped to a workspace need the workspace ID on every request.
        workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID")
        self.client = anthropic.Anthropic(
            default_headers={"anthropic-workspace-id": workspace} if workspace else None)

    @staticmethod
    def _encode(frame_bgr: np.ndarray) -> str:
        h, w = frame_bgr.shape[:2]
        scale = SEND_MAX_SIDE / max(h, w)
        if scale < 1:
            frame_bgr = cv2.resize(frame_bgr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 88])
        if not ok:
            raise RuntimeError("JPEG encoding failed")
        return base64.standard_b64encode(buf.tobytes()).decode("utf-8")

    def analyze(self, frame_bgr: np.ndarray, model: str) -> dict:
        image_b64 = self._encode(frame_bgr)
        request = dict(
            model=model,
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}},
                    {"type": "text", "text": "What food is in this photo, and roughly how many grams and kcal of each? "
                                             "If there is no food, tell me what you see."},
                ],
            }],
        )
        output_format = {"type": "json_schema", "schema": RESULT_SCHEMA}

        if model.startswith("claude-haiku"):
            # Haiku 4.5: no effort parameter, thinking off by default — fastest.
            request["output_config"] = {"format": output_format}
            response = self.client.messages.create(**request)
        elif model.startswith("claude-opus") or model.startswith("claude-fable"):
            # Opus / Fable: adaptive thinking at low effort, with server-side refusal fallback.
            request["thinking"] = {"type": "adaptive"}
            request["output_config"] = {"effort": "low", "format": output_format}
            response = self.client.beta.messages.create(
                **request, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        else:
            # Sonnet: thinking off — a one-shot visual estimate doesn't need it, and it cuts latency a lot.
            request["thinking"] = {"type": "disabled"}
            request["output_config"] = {"effort": "low", "format": output_format}
            response = self.client.messages.create(**request)

        if response.stop_reason == "refusal":
            raise RuntimeError("Claude declined to process this image")
        if response.stop_reason == "max_tokens":
            raise RuntimeError("Response was truncated (max_tokens)")
        text = next(b.text for b in response.content if b.type == "text")
        return json.loads(text)


# ───────────────────────── Auto-detection ─────────────────────────
class SceneTrigger:
    """Detects the moment a new object enters the frame and holds still.
    Head regions are masked out so a person moving in front of the camera doesn't trigger it."""

    def __init__(self):
        self.bg = None
        self.prev = None
        self.last_capture = None
        self.last_fire = 0.0
        self.stable_since = None
        self.status = "Initialising background…"
        self.progress = 0.0

    @staticmethod
    def _prep(frame):
        h, w = frame.shape[:2]
        small = cv2.resize(frame, (DETECT_W, int(h * DETECT_W / w)))
        return cv2.GaussianBlur(small, (21, 21), 0)  # keep colour: catches objects that differ in hue but not brightness

    @staticmethod
    def _mask(shape, frame_w, head_boxes):
        mask = np.full(shape[:2], 255, np.uint8)
        s = DETECT_W / frame_w
        for (x, y, w, h) in head_boxes:
            px, py = w * HEAD_MASK_PAD, h * HEAD_MASK_PAD
            cv2.rectangle(mask, (int((x - px) * s), int((y - py) * s)),
                          (int((x + w + px) * s), int((y + h + py) * s)), 0, -1)
        return mask

    @staticmethod
    def _ratio(a, b, mask):
        diff = cv2.absdiff(a, b).max(axis=2)
        _, th = cv2.threshold(diff, PIXEL_DIFF_TH, 255, cv2.THRESH_BINARY)
        th = cv2.bitwise_and(th, mask)
        return float(np.count_nonzero(th)) / max(1, np.count_nonzero(mask))

    def reset(self):
        self.bg = None
        self.prev = None
        self.last_capture = None
        self.stable_since = None

    def update(self, frame, head_boxes=()) -> bool:
        """Returns True when a photo should be taken."""
        g = self._prep(frame)
        if self.bg is None:
            self.bg = g.astype("float32")
            self.prev = g
            self.status = "Background set — monitoring"
            return False

        mask = self._mask(g.shape, frame.shape[1], head_boxes)
        fg = self._ratio(g, cv2.convertScaleAbs(self.bg), mask)
        motion = self._ratio(g, self.prev, mask)
        self.prev = g
        now = time.time()

        if motion > MOTION_RATIO_TH:
            self.stable_since = None
            self.progress = 0.0
            self.status = "Motion detected…"
            return False

        if self.stable_since is None:
            self.stable_since = now

        if fg < EMPTY_RATIO_TH:
            # empty scene: slowly adapt to lighting and re-arm for the next object
            cv2.accumulateWeighted(g, self.bg, 0.05)
            self.last_capture = None
            self.progress = 0.0
            self.status = "Monitoring (scene empty)"
            return False

        if fg < FG_RATIO_TH:
            self.progress = 0.0
            self.status = "Monitoring"
            return False

        if self.last_capture is not None and self._ratio(g, self.last_capture, mask) < RECAPTURE_RATIO_TH:
            self.progress = 0.0
            self.status = "Already analysed — show a different item"
            return False

        if now - self.last_fire < AUTO_COOLDOWN_S:
            self.status = f"Cooling down… {AUTO_COOLDOWN_S - (now - self.last_fire):.1f} s"
            return False

        held = now - self.stable_since
        self.progress = min(1.0, held / STABLE_SECONDS)
        self.status = f"Object found — hold still… {int(self.progress * 100)}%"
        if held >= STABLE_SECONDS:
            self.last_capture = g
            self.last_fire = now
            self.stable_since = None
            self.progress = 0.0
            return True
        return False


# ───────────────────────── Data ─────────────────────────
@dataclass
class Detection:
    id: int
    timestamp: datetime
    frame: np.ndarray             # already face-blurred
    model: str
    thumb: tuple = None
    status: str = "pending"       # pending | food | nonfood | error
    result: dict = field(default_factory=dict)
    error: str = ""
    image_path: str = ""
    latency: float = 0.0


# ───────────────────────── GUI ─────────────────────────
class App:
    def __init__(self, root: tk.Tk, camera_index: int, save_images: bool):
        self.root = root
        self.save_images = save_images
        self.cap = cv2.VideoCapture(camera_index, cv2.CAP_AVFOUNDATION)
        if not self.cap.isOpened():
            self.cap = cv2.VideoCapture(camera_index)
        if not self.cap.isOpened():
            raise SystemExit(
                f"Cannot open camera {camera_index}.\n"
                "Allow camera access for Terminal / VS Code / Python in "
                "System Settings → Privacy & Security → Camera."
            )
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

        self.has_key = has_credentials()
        self.recognizer = FoodRecognizer()
        self.trigger = SceneTrigger()
        self.faces = FaceBlurrer()
        self.detections: list[Detection] = []
        self.results_q: queue.Queue = queue.Queue()
        self.next_id = 1
        self.marquee_offset = 0.0
        self.flash_until = 0.0
        self.auto_mode = tk.BooleanVar(value=True)
        self.blur_faces = tk.BooleanVar(value=True)
        self.preset = tk.StringVar(value=DEFAULT_PRESET)
        self.latest_frame = None      # face-blurred when blurring is on
        self.pending = 0
        self.strip_paused = False
        self._video_item = None
        self._last_key_warning = 0.0

        CAPTURE_DIR.mkdir(exist_ok=True)
        LOG_FILE.parent.mkdir(exist_ok=True)

        self._build_ui()
        self._bind_keys()
        self.root.after(10, self._tick)
        self.root.after(100, self._poll_results)
        self._log_line(f"System started   camera: {camera_index}   model: {self._model()}   "
                       f"face detection: {self.faces.backend}", "muted")
        if not self.has_key:
            self._log_line("⚠️ ANTHROPIC_API_KEY is not set, so photos cannot be analysed. "
                           "Quit, run `export ANTHROPIC_API_KEY=sk-ant-...` in this terminal, then start again.", "error")
        self._log_line("Hold food, food waste or a picture of food in front of the camera for ~1 s to capture "
                       "it automatically, or press Space. Drag the divider to resize this panel.", "muted")

    def _model(self):
        return MODEL_PRESETS[self.preset.get()]

    # ---------- UI ----------
    def _build_ui(self):
        self.root.title("From Bin to Menu — Food Waste Camera")
        self.root.configure(bg=BG)
        self.root.geometry("1400x900")
        self.root.minsize(900, 600)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TCheckbutton", background=PANEL, foreground=FG)
        style.map("TCheckbutton", background=[("active", PANEL)])
        style.configure("TButton", padding=6)

        self.log_font = tkfont.Font(family="Menlo", size=12)
        self.log_bold = tkfont.Font(family="Menlo", size=12, weight="bold")

        # Header bar
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=16, pady=(12, 4))
        tk.Label(header, text="From Bin to Menu", font=("Helvetica", 20, "bold"), fg=FG, bg=BG).pack(side="left")
        tk.Label(header, text="  AI Job 1 · SEE — Claude reads the bin", font=("Helvetica", 13), fg=MUTED, bg=BG).pack(side="left")
        self.clock = tk.Label(header, font=("Menlo", 13), fg=MUTED, bg=BG)
        self.clock.pack(side="right")
        if not self.has_key:
            tk.Label(self.root, text="ANTHROPIC_API_KEY not set — recognition is disabled", bg=RED, fg="white",
                     font=("Helvetica", 13, "bold")).pack(fill="x", padx=16)

        # Draggable divider between the camera side and the log side
        self.paned = tk.PanedWindow(self.root, orient="horizontal", bg=BG, sashwidth=10,
                                    sashrelief="flat", opaqueresize=True, bd=0)
        self.paned.pack(fill="both", expand=True, padx=16, pady=(4, 12))

        # Left: main video + scrolling icon strip
        left = tk.Frame(self.paned, bg=BG)
        self.video = tk.Canvas(left, bg="black", highlightthickness=0)
        self.video.pack(fill="both", expand=True)

        controls = tk.Frame(left, bg=PANEL)
        controls.pack(fill="x", pady=(8, 0))
        ttk.Button(controls, text="📸 Capture now (Space)", command=self.manual_capture).pack(side="left", padx=6, pady=6)
        ttk.Button(controls, text="↺ Reset background (R)", command=self.reset_background).pack(side="left", padx=4)
        ttk.Checkbutton(controls, text="Auto-detect (A)", variable=self.auto_mode).pack(side="left", padx=6)
        ttk.Checkbutton(controls, text="Blur faces", variable=self.blur_faces).pack(side="left", padx=6)
        tk.Label(controls, text="Model:", fg=MUTED, bg=PANEL).pack(side="left", padx=(10, 2))
        combo = ttk.Combobox(controls, textvariable=self.preset, values=list(MODEL_PRESETS),
                             state="readonly", width=20)
        combo.pack(side="left")
        combo.bind("<<ComboboxSelected>>", lambda e: (self._log_line(f"Model switched to {self._model()}", "muted"),
                                                      self.root.focus_set()))

        status_bar = tk.Frame(left, bg=BG)
        status_bar.pack(fill="x", pady=(4, 0))
        self.status_lbl = tk.Label(status_bar, text="", fg=AMBER, bg=BG, font=("Helvetica", 12), anchor="w")
        self.status_lbl.pack(side="left", padx=4)

        self.strip = tk.Canvas(left, height=ICON_SIZE + 44, bg=PANEL, highlightthickness=0)
        self.strip.pack(fill="x", pady=(6, 0))
        self.strip.bind("<Button-1>", self._on_strip_click)
        self.strip.bind("<Enter>", lambda e: setattr(self, "strip_paused", True))
        self.strip.bind("<Leave>", lambda e: setattr(self, "strip_paused", False))

        # Right: log window
        right = tk.Frame(self.paned, bg=PANEL)
        top = tk.Frame(right, bg=PANEL)
        top.pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(top, text="DETECTION LOG", font=("Helvetica", 14, "bold"), fg=FG, bg=PANEL).pack(side="left")
        ttk.Button(top, text="A+", width=3, command=lambda: self._zoom_log(+1)).pack(side="right")
        ttk.Button(top, text="A−", width=3, command=lambda: self._zoom_log(-1)).pack(side="right", padx=4)
        self.stats_lbl = tk.Label(right, text="", font=("Helvetica", 12), fg=MUTED, bg=PANEL, justify="left")
        self.stats_lbl.pack(anchor="w", padx=12, pady=(2, 6))

        log_frame = tk.Frame(right, bg=PANEL)
        log_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.log = tk.Text(log_frame, width=20, bg="#0b0d11", fg=FG, insertbackground=FG,
                           font=self.log_font, wrap="word", relief="flat", padx=10, pady=8)
        sb = ttk.Scrollbar(log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set, state="disabled")
        self.log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for tag, color in (("muted", MUTED), ("food", GREEN), ("nonfood", RED), ("pending", AMBER),
                           ("error", RED), ("time", BLUE), ("head", FG)):
            self.log.tag_configure(tag, foreground=color)
        self.log.tag_configure("head", font=self.log_bold)
        self.log.tag_configure("highlight", background="#26303f")

        self.paned.add(left, minsize=480, stretch="always")
        self.paned.add(right, minsize=260, stretch="always")
        self.root.after(50, lambda: self.paned.sash_place(0, int(self.paned.winfo_width() * 0.62), 0))

    def _zoom_log(self, step):
        size = max(8, min(28, self.log_font.cget("size") + step))
        self.log_font.configure(size=size)
        self.log_bold.configure(size=size)

    def _bind_keys(self):
        self.root.bind("<space>", lambda e: self.manual_capture())
        self.root.bind("<KeyPress-r>", lambda e: self.reset_background())
        self.root.bind("<KeyPress-a>", lambda e: self.auto_mode.set(not self.auto_mode.get()))
        self.root.bind("<KeyPress-q>", lambda e: self.close())
        self.root.bind("<Escape>", lambda e: self.close())
        self.root.bind("<Command-plus>", lambda e: self._zoom_log(+1))
        self.root.bind("<Command-equal>", lambda e: self._zoom_log(+1))
        self.root.bind("<Command-minus>", lambda e: self._zoom_log(-1))

    # ---------- Main loop ----------
    def _tick(self):
        ok, raw = self.cap.read()
        if ok:
            self.faces.update(raw)   # always tracked: also used to ignore head motion
            frame = self.faces.blur(raw) if self.blur_faces.get() else raw
            self.latest_frame = frame
            if self.auto_mode.get():
                if self.trigger.update(raw, self.faces.boxes):
                    self._capture(frame, auto=True)
            else:
                self.trigger.status = "Auto-detect off (press Space to capture)"
            self._render_video(frame)
        self._render_strip()
        self._update_status()
        self.root.after(15, self._tick)

    def _render_video(self, frame):
        cw, ch = self.video.winfo_width(), self.video.winfo_height()
        if cw < 10 or ch < 10:
            return
        h, w = frame.shape[:2]
        scale = min(cw / w, ch / h)
        disp = cv2.resize(frame, (max(1, int(w * scale)), max(1, int(h * scale))))
        img = Image.fromarray(cv2.cvtColor(disp, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(img)
        if self.trigger.progress > 0:   # hold-still progress bar
            draw.rectangle([0, img.height - 8, int(img.width * self.trigger.progress), img.height], fill=AMBER)
        if time.time() < self.flash_until:   # capture flash
            draw.rectangle([0, 0, img.width - 1, img.height - 1], outline="white", width=12)
        self._video_img = ImageTk.PhotoImage(img)
        if self._video_item is None:
            self._video_item = self.video.create_image(cw // 2, ch // 2, image=self._video_img)
        else:
            self.video.coords(self._video_item, cw // 2, ch // 2)
            self.video.itemconfigure(self._video_item, image=self._video_img)

    def _update_status(self):
        self.clock.configure(text=datetime.now().strftime("%a %d %b %Y  %H:%M:%S"))
        parts = [self.trigger.status]
        if self.blur_faces.get() and self.faces.boxes:
            parts.append(f"{len(self.faces.boxes)} face(s) blurred")
        if self.pending:
            parts.append(f"analysing {self.pending}")
        self.status_lbl.configure(text="   |   ".join(parts))

        food = [d for d in self.detections if d.status == "food"]
        nonfood = sum(1 for d in self.detections if d.status == "nonfood")
        grams = sum(d.result.get("total_grams", 0) for d in food)
        kcal = sum(d.result.get("total_kcal", 0) for d in food)
        done = [d.latency for d in self.detections if d.status in ("food", "nonfood")]
        avg = f"   avg response {sum(done) / len(done):.1f} s" if done else ""
        self.stats_lbl.configure(
            text=f"Captures {len(self.detections)}   food {len(food)}   not food {nonfood}{avg}\n"
                 f"Estimated total: {grams:,.0f} g  /  {kcal:,.0f} kcal"
        )

    # ---------- Capture & recognition ----------
    def manual_capture(self):
        if self.latest_frame is not None:
            self._capture(self.latest_frame, auto=False)

    def reset_background(self):
        self.trigger.reset()
        self._log_line("Background reset (clear the frame so the camera sees an empty scene)", "muted")

    def _capture(self, frame, auto: bool):
        if not self.has_key:
            if time.time() - self._last_key_warning > 10:
                self._last_key_warning = time.time()
                self._log_line("Capture skipped: ANTHROPIC_API_KEY is not set.", "error")
            return
        frame = frame.copy()
        det = Detection(id=self.next_id, timestamp=datetime.now(), frame=frame, model=self._model())
        self.next_id += 1
        det.thumb = self._make_thumb(frame, AMBER, "Analysing…")
        if self.save_images:
            path = CAPTURE_DIR / f"{det.timestamp:%Y%m%d_%H%M%S}_{det.id:04d}.jpg"
            cv2.imwrite(str(path), frame)
            det.image_path = str(path)
        self.detections.append(det)
        self.flash_until = time.time() + 0.25
        self.pending += 1
        self._log_line(f"#{det.id:04d}  {det.timestamp:%H:%M:%S}  "
                       f"{'Auto' if auto else 'Manual'} capture → {det.model}…", "pending")
        threading.Thread(target=self._worker, args=(det,), daemon=True).start()

    def _worker(self, det: Detection):
        start = time.time()
        try:
            result, err = self.recognizer.analyze(det.frame, det.model), None
        except anthropic.AuthenticationError:
            result, err = None, "API key invalid (ANTHROPIC_API_KEY)"
        except anthropic.NotFoundError:
            result, err = None, f"Model {det.model} is not available to this API key"
        except anthropic.RateLimitError:
            result, err = None, "Rate limited — try again shortly"
        except anthropic.APIStatusError as e:
            if "not scoped to a workspace" in str(e.message):
                err = ("This API key has no workspace. Add ANTHROPIC_WORKSPACE_ID=wrkspc_... to .env "
                       "(Console → Settings → Workspaces), or create a key inside a workspace.")
            else:
                err = f"API error {e.status_code}: {e.message}"
            result = None
        except anthropic.APIConnectionError:
            result, err = None, "Network connection failed"
        except Exception as e:  # noqa: BLE001 — shown in the log
            result, err = None, f"{type(e).__name__}: {e}"
        det.latency = time.time() - start
        self.results_q.put((det, result, err))

    def _poll_results(self):
        try:
            while True:
                det, result, err = self.results_q.get_nowait()
                self.pending -= 1
                if err:
                    det.status, det.error = "error", err
                    det.thumb = self._make_thumb(det.frame, RED, "Error")
                else:
                    det.result = result
                    if result.get("is_food"):
                        det.status = "food"
                        det.thumb = self._make_thumb(det.frame, GREEN, f"{result.get('total_kcal', 0):.0f} kcal")
                    else:
                        det.status = "nonfood"
                        det.thumb = self._make_thumb(det.frame, RED, "Not food")
                self._log_detection(det)
                self._append_jsonl(det)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_results)

    # ---------- Scrolling icon strip ----------
    def _make_thumb(self, frame, color, caption):
        img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        w, h = img.size
        side = min(w, h)
        img = img.crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2))
        img = img.resize((ICON_SIZE, ICON_SIZE), Image.LANCZOS)
        canvas = Image.new("RGB", (ICON_SIZE + 8, ICON_SIZE + 8), color)
        canvas.paste(img, (4, 4))
        return ImageTk.PhotoImage(canvas), caption, color

    def _render_strip(self):
        c = self.strip
        c.delete("all")
        width = max(c.winfo_width(), 100)
        cell = ICON_SIZE + 8 + ICON_GAP
        n = len(self.detections)
        if n == 0:
            c.create_text(width // 2, (ICON_SIZE + 44) // 2, text="Captured photos will scroll past here as icons",
                          fill=MUTED, font=("Helvetica", 13))
            return

        if not self.strip_paused:
            self.marquee_offset += MARQUEE_SPEED
        total = n * cell
        if total <= width:
            # few icons: newest docks at the right edge
            for i, det in enumerate(reversed(self.detections)):
                self._draw_icon(det, width - (i + 1) * cell)
        else:
            # icons keep sliding left and loop once they overflow
            x = -(self.marquee_offset % total)
            while x < width:
                for det in self.detections:   # oldest → newest, scrolling left
                    if -cell < x < width:
                        self._draw_icon(det, x)
                    x += cell

    def _draw_icon(self, det, x):
        img, caption, color = det.thumb
        y = 8
        cx = x + ICON_GAP // 2 + (ICON_SIZE + 8) // 2
        tag = (f"det{det.id}",)
        self.strip.create_image(x + ICON_GAP // 2, y, image=img, anchor="nw", tags=tag)
        self.strip.create_text(cx, y + ICON_SIZE + 18, text=f"#{det.id} {caption}", fill=color,
                               font=("Helvetica", 11, "bold"), tags=tag)
        self.strip.create_text(cx, y + ICON_SIZE + 32, text=det.timestamp.strftime("%H:%M:%S"), fill=MUTED,
                               font=("Helvetica", 10), tags=tag)

    def _on_strip_click(self, event):
        item = self.strip.find_closest(event.x, event.y)
        if not item:
            return
        for tag in self.strip.gettags(item[0]):
            if tag.startswith("det"):
                self._highlight_log(int(tag[3:]))
                self._show_detail(int(tag[3:]))
                return

    def _show_detail(self, det_id):
        det = next((d for d in self.detections if d.id == det_id), None)
        if det is None:
            return
        win = tk.Toplevel(self.root, bg=PANEL)
        win.title(f"#{det.id:04d}  {det.timestamp:%a %d %b %Y  %H:%M:%S}")
        img = Image.fromarray(cv2.cvtColor(det.frame, cv2.COLOR_BGR2RGB))
        img.thumbnail((640, 480))
        photo = ImageTk.PhotoImage(img)
        lbl = tk.Label(win, image=photo, bg=PANEL)
        lbl.image = photo
        lbl.pack(padx=10, pady=10)
        tk.Label(win, text=self._format_result(det), justify="left", fg=FG, bg=PANEL,
                 font=self.log_font, wraplength=640).pack(anchor="w", padx=14, pady=(0, 12))

    # ---------- Log ----------
    def _log_line(self, text, tag="head"):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", tag)
        self.log.configure(state="disabled")
        self.log.see("end")

    def _format_result(self, det: Detection) -> str:
        if det.status == "error":
            return f"❌ Recognition failed: {det.error}"
        if det.status == "pending":
            return "Analysing…"
        r = det.result
        if not r.get("is_food"):
            objs = ", ".join(r.get("non_food_objects", [])) or "(unidentified)"
            return f"🚫 NOT FOOD\n   Detected: {objs}\n   {r.get('summary', '')}"
        source = {"picture": " (picture of food)", "packaged": " (packaged)"}.get(r.get("food_source"), "")
        lines = [f"🍱 FOOD{source}"]
        for it in r.get("items", []):
            lines.append(f"   • {it['name']}  ≈ {it['estimated_grams']:.0f} g  "
                         f"/ {it['estimated_kcal']:.0f} kcal  [{it['confidence']}]")
        lines.append(f"   Total ≈ {r.get('total_grams', 0):.0f} g / {r.get('total_kcal', 0):.0f} kcal")
        if r.get("summary"):
            lines.append(f"   {r['summary']}")
        if r.get("notes"):
            lines.append(f"   Notes: {r['notes']}")
        return "\n".join(lines)

    def _log_detection(self, det: Detection):
        self.log.configure(state="normal")
        start = self.log.index("end-1c")
        self.log.insert("end", "─" * 36 + "\n", "muted")
        self.log.insert("end", f"#{det.id:04d}  ", "head")
        self.log.insert("end", det.timestamp.strftime("%a %d %b %Y  %H:%M:%S"), "time")
        self.log.insert("end", f"   {det.latency:.1f} s · {det.model}\n", "muted")
        self.log.insert("end", self._format_result(det) + "\n", det.status)
        self.log.mark_set(f"det{det.id}", start)
        self.log.mark_gravity(f"det{det.id}", "left")
        self.log.configure(state="disabled")
        self.log.see("end")

    def _highlight_log(self, det_id):
        self.log.tag_remove("highlight", "1.0", "end")
        mark = f"det{det_id}"
        if mark in self.log.mark_names():
            self.log.tag_add("highlight", mark, f"{mark} +8 lines")
            self.log.see(mark)

    def _append_jsonl(self, det: Detection):
        rec = {
            "id": det.id,
            "timestamp": det.timestamp.isoformat(timespec="seconds"),
            "status": det.status,
            "image": det.image_path,
            "result": det.result,
            "error": det.error,
            "model": det.model,
            "latency_s": round(det.latency, 2),
        }
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def close(self):
        self.cap.release()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description="From Bin to Menu — food-waste recognition camera")
    parser.add_argument("--camera", type=int, default=0, help="camera index (default 0 = built-in camera)")
    parser.add_argument("--no-save", action="store_true", help="do not save captured photos (privacy mode)")
    args = parser.parse_args()

    if not has_credentials():
        print("⚠️  ANTHROPIC_API_KEY not set — recognition is disabled. Run: export ANTHROPIC_API_KEY=sk-ant-...",
              file=sys.stderr)

    root = tk.Tk()
    App(root, args.camera, save_images=not args.no_save)
    root.mainloop()


if __name__ == "__main__":
    main()

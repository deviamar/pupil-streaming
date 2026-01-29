from plugin import Plugin
import csv
import logging
import os
import time
import cv2
from pyglui.cygl.utils import RGBA
from pyglui.pyfontstash import fontstash


logger = logging.getLogger(__name__)

TARGET_EYE_ID = 1  # <-- set to 0 or 1 (whichever eye window is the one you want)
CONF_CUTOFF = 0.60   # 60%


class PupilCoordOverlay(Plugin):
    order = 0.9

    def __init__(self, g_pool):
        super().__init__(g_pool)

        # ---- overlay state (must exist before gl_display is called) ----
        self._label = ""
        self._cxcy = None
        self._w_h = (1.0, 1.0)

        self.process_eye_id = getattr(self.g_pool, "eye_id", None)
        self.eye_label = f"eye{self.process_eye_id}" if self.process_eye_id in (0, 1) else "unknown-eye"

        base_dir = os.path.expanduser("~/pupil_capture_settings")
        os.makedirs(base_dir, exist_ok=True)

        # ---- timestamped filename ----
        timestr = time.strftime("%Y-%m-%d_%H-%M-%S")
        self.csv_path = os.path.join(
            base_dir,
            f"pupil_coords_{self.eye_label}_{timestr}.csv"
        )

        self._ensure_csv_header()

        logger.info(f"PupilCoordOverlay loaded for {self.eye_label}")
        logger.info(f"Logging pupil coords to {self.csv_path}")


    def recent_events(self, events):
        datums, source_key = self._get_pupil_datums(events)
        if not datums:
            return

        # Choose most recent datum for target eye
        d_target = None
        for d in reversed(datums):
            eye_id = d.get("id", d.get("eye_id", None))
            if TARGET_EYE_ID is None or eye_id == TARGET_EYE_ID:
                d_target = d
                break
        if d_target is None:
            return

        norm = d_target.get("norm_pos")
        if not norm:
            return

        conf = float(d_target.get("confidence", -1.0))

        # If confidence is low: show warning, do NOT log, do NOT write CSV
        if conf < CONF_CUTOFF:
            cutoff_pct = int(round(CONF_CUTOFF * 100))
            self._label = f"confidence below {cutoff_pct}%"
            self._cxcy = None
            return

        x_norm, y_norm = norm
        w, h = self._frame_size()
        x_px = x_norm * w
        y_px = (1.0 - y_norm) * h

        ts = float(d_target.get("timestamp", time.time()))
        method = d_target.get("method", "")

        eye_id = d_target.get("id", d_target.get("eye_id", "unknown"))
        eye_str = f"eye{eye_id}"

        label = f"{eye_str}: ({x_px:.1f},{y_px:.1f}) px  ({x_norm:.3f},{y_norm:.3f}) norm"

        # For on-screen overlay (gl_display)
        self._w_h = (w, h)
        self._cxcy = (x_px, y_px)
        self._label = label

        # Log + CSV only when confident
        logger.info(label)
        self._append_csv(ts, source_key, x_norm, y_norm, x_px, y_px, conf, method)


    def gl_display(self):
        label = getattr(self, "_label", "")
        if not label:
            return

        # Lazy init font if needed (depends on Pupil build)
        if not hasattr(self, "_glfont") or self._glfont is None:
            from pyglui.pyfontstash import fontstash
            self._glfont = fontstash.Context()
            self._font_size = getattr(self, "_font_size", 28)

        self._glfont.push_state()
        self._glfont.set_size(getattr(self, "_font_size", 28))
        self._glfont.set_color_float((1.0, 1.0, 1.0, 1.0))
        self._glfont.draw_text(10, 10, label)
        self._glfont.pop_state()


    def _get_pupil_datums(self, events):
        for key in ("pupil", "pupil_positions", "pupil.0", "pupil.1"):
            v = events.get(key)
            if isinstance(v, list) and v:
                return v, key
        return [], ""

    def _frame_size(self):
        cap = getattr(self.g_pool, "capture", None)
        fs = getattr(cap, "frame_size", None)
        if fs and len(fs) == 2:
            return float(fs[0]), float(fs[1])
        return 1.0, 1.0

    def _ensure_csv_header(self):
        if os.path.exists(self.csv_path) and os.path.getsize(self.csv_path) > 0:
            return
        with open(self.csv_path, "w", newline="") as f:
            csv.writer(f).writerow(
                ["timestamp","eye","source_key","x_norm","y_norm","x_px","y_px","confidence","method"]
            )

    def _append_csv(self, ts, source_key, x_norm, y_norm, x_px, y_px, conf, method):
        with open(self.csv_path, "a", newline="") as f:
            csv.writer(f).writerow(
                [f"{ts:.6f}", self.eye_label, source_key,
                 f"{x_norm:.6f}", f"{y_norm:.6f}",
                 f"{x_px:.3f}", f"{y_px:.3f}",
                 f"{conf:.3f}", method]
            )

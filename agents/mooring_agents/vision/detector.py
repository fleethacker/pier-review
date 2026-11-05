"""Optional trained bollard detector (YOLO weights) used as a pixel-location source for the Berth Map agent.

Disabled unless BOLLARD_MODEL_PATH points at a weights file *and* the optional `ultralytics` package is installed
(`uv sync --extra detector`). Detections are only proposals: the agent still projects them through modeling with the
caller's pier-face anchors and every item requires human confirmation.
"""
import asyncio
import io
import os
from functools import lru_cache

from mooring.core.schemas.berth_drafts import ImageFitting

# The catalog has no 'bollard' kind; a pier bollard is modeled as a bitt unless overridden.
FITTING_KIND = os.environ.get('BOLLARD_FITTING_KIND', 'bitt')


class DetectorUnavailable(Exception):
    pass


class BollardDetector:
    def __init__(self, weights: str, min_conf: float, device: str | None = None):
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise DetectorUnavailable('ultralytics is not installed') from exc
        self.model, self.min_conf, self.device = YOLO(weights), min_conf, device
        self.version = os.path.basename(weights)

    def detect(self, image: bytes) -> list[tuple[ImageFitting, tuple[float, float, float, float]]]:
        from PIL import Image
        img = Image.open(io.BytesIO(image)).convert('RGB')
        result = self.model.predict(img, conf=self.min_conf, device=self.device, verbose=False)[0]
        out = []
        for i, (xyxy, conf) in enumerate(zip(result.boxes.xyxy.tolist(), result.boxes.conf.tolist()), 1):
            x0, y0, x1, y1 = xyxy
            fitting = ImageFitting(item_id=f'DET{i}', kind=FITTING_KIND, confidence=float(conf),
                                   center_px=((x0 + x1) / 2, (y0 + y1) / 2))
            out.append((fitting, (x0, y0, x1 - x0, y1 - y0)))
        return out

    async def detect_async(self, image: bytes):
        return await asyncio.to_thread(self.detect, image)


@lru_cache(maxsize=1)
def _load(path: str, min_conf: float):
    return BollardDetector(path, min_conf)


def get_detector() -> BollardDetector | None:
    path = os.environ.get('BOLLARD_MODEL_PATH')
    if not path:
        return None
    if not os.path.isfile(path):
        raise DetectorUnavailable(f'BOLLARD_MODEL_PATH does not exist: {path}')
    return _load(path, float(os.environ.get('BOLLARD_MIN_CONF', '0.25')))

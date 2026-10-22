import base64
import binascii
import hashlib
import io
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BYTES = 3 * 1024 * 1024
MAX_PIXELS = 8_000_000


class VisionError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass
class Picture:
    png: bytes
    width: int
    height: int
    digest: str


def normalize(raw: bytes) -> Picture:
    if not raw or len(raw) > MAX_BYTES:
        raise VisionError("VISION.IMAGE_LIMIT")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw), formats=["PNG", "JPEG", "WEBP"]) as source:
                if source.width * source.height > MAX_PIXELS or max(source.size) > 8192:
                    raise VisionError("VISION.IMAGE_LIMIT")
                if getattr(source, "n_frames", 1) != 1:
                    raise VisionError("VISION.ANIMATION_DENIED")
                source.load()
                image = ImageOps.exif_transpose(source).convert("RGBA")
                background = Image.new("RGBA", image.size, "white")
                background.alpha_composite(image)
                image = background.convert("RGB")
                image.thumbnail((2000, 2000))
                output = io.BytesIO()
                image.save(output, "PNG")  # No EXIF, filename or metadata is carried forward.
                png = output.getvalue()
                if len(png) > MAX_BYTES:
                    raise VisionError("VISION.IMAGE_LIMIT")
                return Picture(png, image.width, image.height, hashlib.sha256(png).hexdigest())
    except VisionError:
        raise
    except (
        OSError,
        ValueError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise VisionError("VISION.INVALID_IMAGE") from None


def decode(value: str) -> Picture:
    if len(value) > (MAX_BYTES * 4 // 3 + 4):
        raise VisionError("VISION.IMAGE_LIMIT")
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise VisionError("VISION.INVALID_IMAGE") from None
    return normalize(raw)

import io
import warnings

from django.conf import settings
from PIL import Image, ImageOps, UnidentifiedImageError


def normalize_image(upload):
    if upload.size > settings.MAX_IMAGE_BYTES:
        raise ValueError(f"Your image must be under {settings.MAX_IMAGE_BYTES // 1048576} MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(upload) as source:
                if source.format not in {"PNG", "JPEG", "WEBP"}:
                    raise ValueError("Choose a PNG, JPEG or WebP image.")
                if getattr(source, "n_frames", 1) != 1:
                    raise ValueError("Choose a still image, rather than an animated image.")
                if max(source.size) > 4096 or min(source.size) < 64:
                    raise ValueError("Image dimensions must be between 64 and 4096 pixels.")
                source.load()
                corrected = ImageOps.exif_transpose(source).convert("RGBA")
                background = Image.new("RGBA", corrected.size, "white")
                background.alpha_composite(corrected)
                image = background.convert("RGB")
                if settings.GENERATION_BACKEND == "agent":
                    width, height = image.size
                    if width < 320 or height < 180:
                        raise ValueError("Use an image at least 320 by 180 pixels.")
                    if abs(width * 9 - height * 16) > height * 16 * 0.02:
                        raise ValueError("Use a landscape 16:9 image for this video preset.")
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                if settings.GENERATION_BACKEND == "agent" and buffer.tell() > 10 * 1024 * 1024:
                    buffer.close()
                    raise ValueError("The normalized image exceeds the 10 MiB upload limit.")
                buffer.seek(0)
                return buffer, image.width, image.height
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ValueError(
            "This image could not be read. Try another PNG, JPEG or WebP."
        ) from exc

"""Create smaller web copies of supplied photographs; never overwrite originals."""
import sys
from pathlib import Path
from PIL import Image, ImageOps

source = Path(sys.argv[1])
target = Path(__file__).resolve().parents[1] / "dist" / "assets" / "photos"
target.mkdir(parents=True, exist_ok=True)
for name in ("IMG_8655", "IMG_4622", "IMG_4843", "IMG_6514", "IMG_4515"):
    with Image.open(source / f"{name}.JPG") as original:
        image = ImageOps.exif_transpose(original)
        image.thumbnail((1800, 1800), Image.Resampling.LANCZOS)
        options = {"quality": 88, "method": 6}
        if original.info.get("icc_profile"):
            options["icc_profile"] = original.info["icc_profile"]
        destination = target / f"{name}.webp"
        image.save(destination, "WEBP", **options)
        print(f"{destination.name}: {image.width}x{image.height}, {destination.stat().st_size:,} bytes")

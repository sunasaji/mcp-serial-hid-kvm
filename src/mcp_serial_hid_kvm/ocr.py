"""OCR text extraction from screen captures, optimized for terminal content."""

import logging
import re
from pathlib import Path

import pytesseract
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

logger = logging.getLogger(__name__)


class TerminalOCR:
    """OCR engine optimized for terminal/console text."""

    def __init__(self, tesseract_cmd: str | None = None):
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        else:
            possible_paths = [
                r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            ]
            for path in possible_paths:
                if Path(path).exists():
                    pytesseract.pytesseract.tesseract_cmd = path
                    break

        self.tesseract_config = r"--oem 3 --psm 6"

    def preprocess_image(self, image: Image.Image) -> Image.Image:
        """Preprocess image for better OCR accuracy."""
        img = image.convert("L")

        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(2.0)

        img = img.filter(ImageFilter.SHARPEN)

        avg_brightness = sum(img.getdata()) / (img.width * img.height)
        if avg_brightness < 128:
            img = ImageOps.invert(img)

        threshold = 180
        img = img.point(lambda x: 255 if x > threshold else 0, "L")

        new_size = (img.width * 2, img.height * 2)
        img = img.resize(new_size, Image.Resampling.LANCZOS)

        return img

    def extract_text(self, image: Image.Image, preprocess: bool = True) -> str:
        """Extract text from a screen capture.

        Args:
            image: PIL Image
            preprocess: Whether to apply preprocessing

        Returns:
            Extracted text
        """
        if preprocess:
            processed = self.preprocess_image(image)
        else:
            processed = image

        try:
            text = pytesseract.image_to_string(
                processed,
                config=self.tesseract_config,
            )
            return self._postprocess_text(text)
        except Exception as e:
            logger.error(f"OCR failed: {e}")
            return f"[OCR Error: {str(e)}]"

    def _postprocess_text(self, text: str) -> str:
        """Clean up OCR output."""
        lines = text.split("\n")
        cleaned_lines = [line.rstrip() for line in lines]

        result = "\n".join(cleaned_lines)
        result = re.sub(r"\n{4,}", "\n\n\n", result)

        safe_corrections = {
            " |s ": " ls ",
            " |s\n": " ls\n",
            "\n|s ": "\nls ",
        }
        for wrong, correct in safe_corrections.items():
            result = result.replace(wrong, correct)

        return result.strip()

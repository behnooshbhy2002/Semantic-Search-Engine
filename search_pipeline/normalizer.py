# Persian text normalization
# Converts Arabic-script variants to their standard Persian equivalents
# and strips zero-width characters that cause silent mismatches.

try:
    from hazm import Normalizer
    _hazm = Normalizer()
    HAS_HAZM = True
except ImportError:
    HAS_HAZM = False


def normalize(text: str) -> str:
    """
    Clean and normalize Persian text.

    If hazm is installed, delegates to its full normalizer.
    Otherwise applies a minimal manual substitution set that covers
    the most common Arabic/Persian character conflicts.
    """
    if not text:
        return ""

    if HAS_HAZM:
        return _hazm.normalize(text)

    # Replace Arabic letter variants with Persian equivalents
    text = text.replace("ك", "ک").replace("ي", "ی").replace("ة", "ه")
    # Remove zero-width non-joiners and right-to-left marks
    text = text.replace("\u200c", " ").replace("\u200f", "")
    return text.strip()
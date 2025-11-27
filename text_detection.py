import os
from typing import Tuple
import numpy as np
import cv2 as cv
import pydicom
from pydicom.pixel_data_handlers.util import apply_voi_lut

try:
    from skimage.restoration import inpaint
    SKIMAGE_OK = True
except Exception:
    SKIMAGE_OK = False


def _display_u8(ds: pydicom.dataset.FileDataset) -> np.ndarray:
    arr = ds.pixel_array
    try:
        arr = apply_voi_lut(arr, ds)
    except Exception:
        arr = arr.astype(np.float32)
    arr = arr.astype(np.float32)
    if getattr(ds, "PhotometricInterpretation", "MONOCHROME2") == "MONOCHROME1":
        arr = np.max(arr) - arr
    lo, hi = np.percentile(arr, 0.5), np.percentile(arr, 99.5)
    if hi <= lo:
        lo, hi = float(arr.min()), float(arr.max())
    arr = np.clip((arr - lo) / (hi - lo + 1e-8), 0, 1)
    return (arr * 255.0 + 0.5).astype(np.uint8)


def _bands_mask(shape: Tuple[int, int], pct: dict) -> np.ndarray:
    """Hard-fill common overlay bands by percentage of image size."""
    H, W = shape
    t = int(pct.get('top', 0.18) * H)     # 18% top
    b = int(pct.get('bottom', 0.00) * H)  # 0% bottom by default
    l = int(pct.get('left', 0.00) * W)    # 0% left by default
    r = int(pct.get('right', 0.22) * W)   # 22% right
    mask = np.zeros((H, W), np.uint8)
    if t > 0: mask[:t, :] = 255
    if b > 0: mask[H - b:, :] = 255
    if l > 0: mask[:, :l] = 255
    if r > 0: mask[:, W - r:] = 255
    return mask


class TextPassOrInpaint:
    """
    Deterministic 'banner' text removal:
    - Build a fixed mask on top/right bands (safe defaults)
    - Inpaint those regions on ORIGINAL float data
    - Only PixelData is modified; tags are untouched
    """

    def __init__(self,
                 enable_inpainting: bool = True,
                 strip_pct: dict | None = None):
        self.enable = enable_inpainting and SKIMAGE_OK
        self.strip_pct = strip_pct or {'top': 0.18, 'right': 0.22, 'bottom': 0.0, 'left': 0.0}
        if enable_inpainting and not SKIMAGE_OK:
            print("[TextRemoval] scikit-image not found; inpainting disabled.")

    def __call__(self, in_path: str, out_path: str):
        ds = pydicom.dcmread(in_path, force=True)

        if not self.enable:
            ds.save_as(out_path)
            return

        # Build mask (bands only – guarantees removal)
        disp = _display_u8(ds)  # for sizing only
        mask = _bands_mask(disp.shape[:2], self.strip_pct)

        coverage = 100.0 * (np.count_nonzero(mask) / mask.size)
        print(f"[TextRemoval] Forced bands mask coverage: {coverage:.2f}%")

        if not mask.any():
            ds.save_as(out_path)
            return

        # Inpaint on original float domain
        orig = ds.pixel_array.astype(np.float32)
        vmin, vmax = float(orig.min()), float(orig.max())
        scale = max(vmax - vmin, 1e-8)
        scaled = (orig - vmin) / scale

        mask_bool = mask.astype(bool)
        filled = inpaint.inpaint_biharmonic(scaled, mask_bool, channel_axis=None)
        restored = (filled * scale + vmin)

        # Cast back to stored dtype
        stored_dtype = ds.pixel_array.dtype
        if np.issubdtype(stored_dtype, np.integer):
            info = np.iinfo(stored_dtype)
            restored = np.clip(restored, info.min, info.max)
        restored = restored.astype(stored_dtype)

        ds.PixelData = restored.tobytes()
        ds.Rows, ds.Columns = restored.shape[:2]
        ds.save_as(out_path)
        print(f"[TextRemoval] Inpaint complete -> {os.path.basename(out_path)}")
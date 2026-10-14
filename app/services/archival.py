"""
Archival & Storage Optimization Service.
Implements Option 3: Thumbnail and size degradation for old images and invoices.
Reduces disk usage by up to 98% for records created > 3 months ago (or configurable days),
while preserving the visual silhouette and complete order details.
"""
from __future__ import annotations

import io
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Compact inline CSS for archived invoices (replaces ~3.8KB of heavy CSS with ~400B)
COMPACT_INVOICE_CSS = (
    "<style>"
    "body{font-family:monospace;padding:8px;background:#f8fafc;display:flex;justify-content:center}"
    ".slip{width:80mm;border:1px dashed #94a3b8;padding:10px;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,0.1)}"
    ".text-center{text-align:center}.bold{font-weight:bold}"
    ".title{font-size:15px;font-weight:900;text-transform:uppercase}"
    ".subtitle{font-size:10px;color:#475569}"
    ".cod-box{border:2px solid #000;text-align:center;padding:5px;margin:6px 0;background:#f8fafc}"
    ".cod-title{font-size:10px;font-weight:bold}"
    ".cod-amount{font-size:18px;font-weight:900}"
    ".section-title{font-size:10px;font-weight:bold;text-transform:uppercase;margin:4px 0}"
    ".info-row{font-size:11px;line-height:1.3;margin:2px 0}"
    ".info-label{font-weight:bold;display:inline-block;width:70px}"
    ".item-desc{font-size:11px;font-weight:bold;margin:3px 0}"
    ".notes-box{font-size:10px;font-style:italic;color:#334155;background:#f1f5f9;padding:3px;margin-top:3px}"
    ".barcode-placeholder{text-align:center;margin-top:8px;letter-spacing:4px;font-size:12px;font-weight:bold}"
    ".divider{border-top:1px dashed #000;margin:6px 0}"
    ".double-divider{border-top:2px solid #000;margin:6px 0}"
    ".print-btn-bar{position:fixed;bottom:15px;right:15px}"
    ".btn{background:#0f172a;color:#fff;padding:8px 14px;border:none;border-radius:6px;font-weight:bold;cursor:pointer}"
    "@media print{body{padding:0;background:none}.slip{box-shadow:none;border:none;width:100%;padding:0}.print-btn-bar{display:none}}"
    "</style>"
)


def shrink_image_file(
    file_path: Path,
    max_dimension: int = 160,
    quality: int = 50,
) -> dict[str, Any]:
    """
    Shrink an image to a small thumbnail (max_dimension x max_dimension)
    with optimized JPEG compression. Reduces size by ~90-98%.
    """
    try:
        if not file_path.exists() or file_path.stat().st_size == 0:
            return {"status": "skipped_empty", "path": str(file_path)}

        orig_size = file_path.stat().st_size

        # Open and inspect image
        with Image.open(file_path) as img:
            orig_w, orig_h = img.size

            # If already smaller than threshold and tiny in size, skip
            if orig_w <= max_dimension and orig_h <= max_dimension and orig_size < 3000:
                return {
                    "status": "already_shrunk",
                    "path": str(file_path),
                    "old_size": orig_size,
                    "new_size": orig_size,
                    "saved_bytes": 0,
                }

            # Convert to RGB (handles RGBA / Palette / CMYK)
            if img.mode in ("RGBA", "P", "LA"):
                rgb_img = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "RGBA":
                    rgb_img.paste(img, mask=img.split()[3])
                else:
                    rgb_img.paste(img)
                img = rgb_img
            elif img.mode != "RGB":
                img = img.convert("RGB")

            # Create thumbnail preserving aspect ratio
            img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

            # Save optimized JPEG in-memory first
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality, optimize=True)
            new_bytes = buf.getvalue()

        # Only overwrite if new size is actually smaller
        if len(new_bytes) < orig_size:
            with open(file_path, "wb") as f:
                f.write(new_bytes)
            new_size = len(new_bytes)
            saved = orig_size - new_size
            logger.info("image_shrunk", path=str(file_path), old_size=orig_size, new_size=new_size, saved=saved)
            return {
                "status": "shrunk",
                "path": str(file_path),
                "old_size": orig_size,
                "new_size": new_size,
                "saved_bytes": saved,
                "dimensions": f"{img.width}x{img.height}",
            }
        else:
            return {
                "status": "already_optimal",
                "path": str(file_path),
                "old_size": orig_size,
                "new_size": orig_size,
                "saved_bytes": 0,
            }

    except Exception as e:
        logger.error("image_shrink_error", path=str(file_path), error=str(e))
        return {"status": "error", "path": str(file_path), "error": str(e)}


def shrink_invoice_file(file_path: Path) -> dict[str, Any]:
    """
    Shrink an HTML invoice file by replacing heavy CSS boilerplate with compact
    inline styles, stripping comments, and minifying whitespace.
    Preserves 100% of order content, layout, and printing functionality.
    """
    try:
        if not file_path.exists() or file_path.suffix.lower() != ".html":
            return {"status": "skipped", "path": str(file_path)}

        orig_size = file_path.stat().st_size
        content = file_path.read_text(encoding="utf-8")

        # If already archived / shrunk, skip
        if "<!-- ARCHIVED_COMPACT -->" in content:
            return {
                "status": "already_shrunk",
                "path": str(file_path),
                "old_size": orig_size,
                "new_size": orig_size,
                "saved_bytes": 0,
            }

        # 1. Replace large <style> block with compact style
        new_content = re.sub(r"<style>.*?</style>", COMPACT_INVOICE_CSS, content, flags=re.DOTALL)

        # 2. Strip HTML comments
        new_content = re.sub(r"<!--.*?-->", "", new_content, flags=re.DOTALL)

        # 3. Collapse whitespace
        new_content = re.sub(r"\s+", " ", new_content).strip()

        # 4. Add marker
        new_content = f"<!-- ARCHIVED_COMPACT -->\n{new_content}"

        new_bytes_len = len(new_content.encode("utf-8"))

        if new_bytes_len < orig_size:
            file_path.write_text(new_content, encoding="utf-8")
            saved = orig_size - new_bytes_len
            logger.info("invoice_shrunk", path=str(file_path), old_size=orig_size, new_size=new_bytes_len, saved=saved)
            return {
                "status": "shrunk",
                "path": str(file_path),
                "old_size": orig_size,
                "new_size": new_bytes_len,
                "saved_bytes": saved,
            }
        else:
            return {
                "status": "already_optimal",
                "path": str(file_path),
                "old_size": orig_size,
                "new_size": orig_size,
                "saved_bytes": 0,
            }

    except Exception as e:
        logger.error("invoice_shrink_error", path=str(file_path), error=str(e))
        return {"status": "error", "path": str(file_path), "error": str(e)}


def shrink_old_records(
    days: int = 90,
    dry_run: bool = False,
    max_dimension: int = 160,
    quality: int = 50,
) -> dict[str, Any]:
    """
    Main archival function.
    Finds all shoe images and invoice files older than `days` (default 90 days = 3 months)
    and shrinks them down to lightweight archival sizes.
    """
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_ts = cutoff_dt.timestamp()

    # Determine directories to scan (checking both settings and Vercel /tmp if present)
    image_dirs = [settings.UPLOADS_DIR]
    invoice_dirs = [settings.INVOICES_DIR]

    tmp_images = Path("/tmp") / "uploads" / "shoes"
    if tmp_images.exists() and tmp_images not in image_dirs:
        image_dirs.append(tmp_images)

    tmp_invoices = Path("/tmp") / "invoices"
    if tmp_invoices.exists() and tmp_invoices not in invoice_dirs:
        invoice_dirs.append(tmp_invoices)

    image_results: list[dict[str, Any]] = []
    invoice_results: list[dict[str, Any]] = []

    total_images_scanned = 0
    total_invoices_scanned = 0
    images_shrunk_count = 0
    invoices_shrunk_count = 0
    images_bytes_saved = 0
    invoices_bytes_saved = 0

    valid_img_extensions = {".jpg", ".jpeg", ".png", ".webp"}

    # 1. Scan Images
    for d in image_dirs:
        if not d.exists():
            continue
        for file in d.iterdir():
            if file.is_file() and file.suffix.lower() in valid_img_extensions and file.name != ".gitkeep":
                total_images_scanned += 1
                try:
                    mtime = file.stat().st_mtime
                    if mtime <= cutoff_ts:
                        if dry_run:
                            orig_sz = file.stat().st_size
                            est_saved = max(0, orig_sz - 1200)
                            image_results.append({
                                "status": "would_shrink",
                                "path": str(file),
                                "old_size": orig_sz,
                                "estimated_new_size": min(orig_sz, 1200),
                                "estimated_saved_bytes": est_saved,
                            })
                            images_shrunk_count += 1
                            images_bytes_saved += est_saved
                        else:
                            res = shrink_image_file(file, max_dimension=max_dimension, quality=quality)
                            image_results.append(res)
                            if res.get("status") == "shrunk":
                                images_shrunk_count += 1
                                images_bytes_saved += res.get("saved_bytes", 0)
                except Exception as e:
                    logger.warning("file_check_error", file=str(file), error=str(e))

    # 2. Scan Invoices
    for d in invoice_dirs:
        if not d.exists():
            continue
        for file in d.iterdir():
            if file.is_file() and file.suffix.lower() == ".html" and file.name != ".gitkeep":
                total_invoices_scanned += 1
                try:
                    mtime = file.stat().st_mtime
                    if mtime <= cutoff_ts:
                        if dry_run:
                            orig_sz = file.stat().st_size
                            est_saved = max(0, orig_sz - 2400)
                            invoice_results.append({
                                "status": "would_shrink",
                                "path": str(file),
                                "old_size": orig_sz,
                                "estimated_new_size": min(orig_sz, 2400),
                                "estimated_saved_bytes": est_saved,
                            })
                            invoices_shrunk_count += 1
                            invoices_bytes_saved += est_saved
                        else:
                            res = shrink_invoice_file(file)
                            invoice_results.append(res)
                            if res.get("status") == "shrunk":
                                invoices_shrunk_count += 1
                                invoices_bytes_saved += res.get("saved_bytes", 0)
                except Exception as e:
                    logger.warning("file_check_error", file=str(file), error=str(e))

    total_bytes_saved = images_bytes_saved + invoices_bytes_saved

    return {
        "status": "ok",
        "dry_run": dry_run,
        "cutoff_days": days,
        "cutoff_date": cutoff_dt.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "summary": {
            "images_scanned": total_images_scanned,
            "images_shrunk": images_shrunk_count,
            "images_bytes_saved": images_bytes_saved,
            "invoices_scanned": total_invoices_scanned,
            "invoices_shrunk": invoices_shrunk_count,
            "invoices_bytes_saved": invoices_bytes_saved,
            "total_files_shrunk": images_shrunk_count + invoices_shrunk_count,
            "total_bytes_saved": total_bytes_saved,
            "total_kb_saved": round(total_bytes_saved / 1024, 2),
            "total_mb_saved": round(total_bytes_saved / (1024 * 1024), 3),
        },
        "image_details": image_results,
        "invoice_details": invoice_results,
    }

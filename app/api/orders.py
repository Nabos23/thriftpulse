"""
Order management API routes:
- Form presentation (GET /order and GET /)
- Order submission & image handling (POST /api/orders)
- Invoice view & print (GET /invoice/{order_code})
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse

from app.core.config import settings
from app.core.database import insert_order, get_order_by_code, update_order_sync_status
from app.core.logging import get_logger
from app.models.order import Order
from app.services.invoice_generator import save_invoice_file
from app.connectors.google_sheets import get_sheets_sync
from app.connectors.whatsapp_client import get_whatsapp_client

logger = get_logger(__name__)

router = APIRouter(tags=["orders"])


def _notify_owner_task(order: Order, base_url: str) -> None:
    """
    Background worker:
    1. Syncs order to Google Sheets
    2. Sends order card and shoe picture to owner's WhatsApp
    """
    # Step 1: Google Sheets Sync
    try:
        sheets = get_sheets_sync()
        sync_res = sheets.append_order(order)
        synced = (sync_res.get("status") == "ok")
    except Exception as e:
        logger.error("sheets_sync_background_failed", error=str(e), order_code=order.order_code)
        synced = False

    update_order_sync_status_sync_call = getattr(settings, "SYNC_DATABASE_URL", None)
    # Update local DB sync status
    from app.core.database import update_order_sync_status_sync
    update_order_sync_status_sync(order.id, synced, order.invoice_path)

    # Step 2: Notify Owner via WhatsApp (Deterministic Outbound - No Agent)
    wa = get_whatsapp_client()
    owner_phone = settings.OWNER_PHONE_NUMBER

    # Always prioritize public BASE_URL for external links if on localhost
    public_base = settings.BASE_URL if ("localhost" in base_url or "127.0.0.1" in base_url) else base_url
    invoice_url = f"{public_base}/invoice/{order.order_code}"
    image_full_url = f"{public_base}/{order.shoe_image_path.lstrip('/')}" if order.shoe_image_path else ""

    # Mode A: If configured to strictly use Meta Message Template (outside 24h window)
    if settings.USE_TEMPLATE_FOR_ALERTS:
        template_res = wa.send_order_alert_template(
            to=owner_phone,
            order_code=order.order_code,
            customer_name=order.customer_name,
            phone=order.phone_primary,
            city=order.city,
            shoe_item=f"{order.shoe_brand_model} ({order.shoe_size})",
            amount=f"PKR {order.price:,.0f}",
            image_url=image_full_url or None,
            invoice_code=order.order_code,
        )
        logger.info("owner_template_alert_sent", status=template_res.get("status"))
        return

    # Mode B: Standard Free-Form Rich Message (Inside 24h window)
    alert_text = (
        f"🚨 *NEW ORDER RECEIVED!* 🚨\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📦 *Order ID:* {order.order_code}\n"
        f"👤 *Customer:* {order.customer_name}\n"
        f"📞 *Phone:* {order.phone_primary}"
        + (f" (Alt: {order.phone_secondary})" if order.phone_secondary else "") + "\n"
        f"🏙️ *City:* {order.city}\n"
        f"📍 *Address:* {order.full_address}\n"
        f"👟 *Shoe:* {order.shoe_brand_model} (Size: {order.shoe_size})\n"
        f"💵 *Amount:* PKR {order.price:,.0f} ({order.payment_method})\n"
        + (f"📝 *Note:* {order.notes}\n" if order.notes else "") +
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📄 *1-Tap Print Slip:* {invoice_url}\n"
        f"_(Shoe photo attached below)_ 👇"
    )

    send_res = wa.send_text(owner_phone, alert_text)

    # Automatic Fallback: If free-form failed because 24-hour window is closed, try template
    if send_res.get("status") == "error":
        err_str = str(send_res.get("error", ""))
        logger.warning("freeform_failed_trying_template", error=err_str)
        wa.send_order_alert_template(
            to=owner_phone,
            order_code=order.order_code,
            customer_name=order.customer_name,
            phone=order.phone_primary,
            city=order.city,
            shoe_item=f"{order.shoe_brand_model} ({order.shoe_size})",
            amount=f"PKR {order.price:,.0f}",
            image_url=image_full_url or None,
            invoice_code=order.order_code,
        )
    else:
        # Dispatch shoe photo via binary upload (works on Vercel /tmp too)
        if order.shoe_image_path:
            caption = f"👟 Shoe for Order #{order.order_code} - {order.customer_name}"
            filename = Path(order.shoe_image_path).name
            candidates = [
                Path("/tmp") / "uploads" / "shoes" / filename,   # Vercel
                settings.BASE_DIR / "app" / order.shoe_image_path.lstrip("/"),  # local dev
                settings.UPLOADS_DIR / filename,                  # config fallback
            ]
            for disk_path in candidates:
                if disk_path.exists():
                    wa.send_image_file(owner_phone, str(disk_path), caption=caption)
                    break


@router.get("/", response_class=HTMLResponse)
@router.get("/order", response_class=HTMLResponse)
@router.get("/api/index", response_class=HTMLResponse)
@router.get("/api/index/order", response_class=HTMLResponse)
async def get_order_form():
    """Serve the customer order intake form."""
    form_path = Path(__file__).resolve().parent.parent / "templates" / "order_form.html"
    if not form_path.exists():
        raise HTTPException(status_code=404, detail="Order form template missing")
    return HTMLResponse(content=form_path.read_text(encoding="utf-8"))


@router.post("/api/orders")
async def create_order(
    request: Request,
    background_tasks: BackgroundTasks,
    customer_name: str = Form(...),
    phone_primary: str = Form(...),
    phone_secondary: Optional[str] = Form(""),
    city: str = Form(...),
    area: str = Form(...),
    address: str = Form(...),
    nearest_landmark: Optional[str] = Form(""),
    shoe_brand_model: str = Form(...),
    shoe_size: str = Form(...),
    price: float = Form(...),
    payment_method: str = Form("Cash on Delivery"),
    notes: Optional[str] = Form(""),
    shoe_photo: UploadFile = File(...),
):
    """
    Handle order submission:
    - Save compressed shoe image
    - Insert record into SQLite
    - Generate printable waybill/invoice
    - Schedule Google Sheets sync + Owner WhatsApp notification
    """
    # Ensure directories exist
    os.makedirs(settings.UPLOADS_DIR, exist_ok=True)
    os.makedirs(settings.INVOICES_DIR, exist_ok=True)

    # Save uploaded image
    unique_suffix = uuid.uuid4().hex[:8]
    ext = Path(shoe_photo.filename or "photo.jpg").suffix.lower() or ".jpg"
    image_filename = f"shoe_{unique_suffix}{ext}"
    image_disk_path = settings.UPLOADS_DIR / image_filename

    image_bytes = await shoe_photo.read()
    with open(image_disk_path, "wb") as f:
        f.write(image_bytes)

    relative_image_path = f"/static/uploads/shoes/{image_filename}"

    # Insert order in SQLite
    order_data = {
        "customer_name": customer_name.strip(),
        "phone_primary": phone_primary.strip(),
        "phone_secondary": (phone_secondary or "").strip(),
        "city": city.strip(),
        "area": area.strip(),
        "address": address.strip(),
        "nearest_landmark": (nearest_landmark or "").strip(),
        "shoe_brand_model": shoe_brand_model.strip(),
        "shoe_size": shoe_size.strip(),
        "price": price,
        "payment_method": payment_method.strip(),
        "notes": (notes or "").strip(),
        "shoe_image_path": relative_image_path,
        "status": "Pending",
        "sheets_synced": False,
    }

    order = await insert_order(order_data)

    # Generate thermal invoice HTML
    invoice_rel_path = save_invoice_file(order)
    order.invoice_path = invoice_rel_path

    # Determine base URL for links
    host_header = request.headers.get("host") or f"{settings.HOST}:{settings.PORT}"
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    current_base_url = f"{scheme}://{host_header}" if host_header else settings.BASE_URL

    # Dispatch Google Sheets sync & WhatsApp notification in background
    background_tasks.add_task(_notify_owner_task, order, current_base_url)

    logger.info("order_created_successfully", order_code=order.order_code, customer=order.customer_name)

    return JSONResponse(
        status_code=200,
        content={
            "status": "ok",
            "message": "Order created successfully",
            "order": order.model_dump(),
        },
    )


@router.get("/invoice/{order_code}", response_class=HTMLResponse)
async def view_invoice(order_code: str):
    """View and print the 80mm thermal waybill for packing/courier."""
    order = await get_order_by_code(order_code)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    invoice_file = settings.INVOICES_DIR / f"{order.order_code}.html"
    if invoice_file.exists():
        return HTMLResponse(content=invoice_file.read_text(encoding="utf-8"))

    # Generate if not on disk
    from app.services.invoice_generator import generate_thermal_invoice_html
    return HTMLResponse(content=generate_thermal_invoice_html(order))


@router.post("/api/maintenance/shrink")
@router.get("/api/maintenance/shrink")
@router.post("/api/index/maintenance/shrink")
@router.get("/api/index/maintenance/shrink")
async def shrink_archival_files(
    days: int = 90,
    dry_run: bool = False,
    max_dimension: int = 160,
    quality: int = 50,
):
    """
    Archival maintenance route (Option 3):
    Checks all shoe photos and HTML invoices created > `days` ago (default 90 days = 3 months)
    and reduces their sizes:
    1. Images are converted to lightweight micro-thumbnails (saving ~90-98% disk space).
    2. Invoices are minified and streamlined (saving ~50% disk space).
    
    Parameters:
    - days: Age threshold in days (default: 90 = 3 months). Pass days=0 to shrink all existing files.
    - dry_run: If True, previews what would be shrunk and calculates savings without modifying disk.
    - max_dimension: Max width/height for thumbnail images (default: 160px).
    - quality: JPEG quality for shrunk images (default: 50).
    """
    import asyncio
    from app.services.archival import shrink_old_records

    result = await asyncio.to_thread(
        shrink_old_records,
        days=days,
        dry_run=dry_run,
        max_dimension=max_dimension,
        quality=quality,
    )
    return JSONResponse(status_code=200, content=result)


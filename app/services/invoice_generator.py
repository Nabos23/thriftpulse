"""
Invoice and 80mm Thermal Waybill generator for Thrifted Shoes.
Creates printable HTML and viewable receipts for riders and packers.
"""
from __future__ import annotations

import os
from pathlib import Path
from app.core.config import settings
from app.core.logging import get_logger
from app.models.order import Order

logger = get_logger(__name__)


def generate_thermal_invoice_html(order: Order) -> str:
    """
    Generate an 80mm-width thermal receipt HTML optimized for instant mobile printing.
    """
    cod_highlight = f"PKR {order.price:,.0f}"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Shipping Slip - {order.order_code}</title>
  <style>
    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      font-family: 'Courier New', Courier, monospace, system-ui;
    }}
    body {{
      background: #f1f5f9;
      display: flex;
      justify-content: center;
      padding: 15px;
    }}
    .slip {{
      width: 80mm;
      background: #ffffff;
      padding: 12px 14px;
      border: 1px dashed #94a3b8;
      box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);
    }}
    .text-center {{ text-align: center; }}
    .text-right {{ text-align: right; }}
    .bold {{ font-weight: bold; }}
    .title {{
      font-size: 16px;
      font-weight: 900;
      letter-spacing: 1px;
      text-transform: uppercase;
      margin-bottom: 2px;
    }}
    .subtitle {{
      font-size: 10px;
      color: #475569;
      margin-bottom: 8px;
    }}
    .divider {{
      border-top: 1px dashed #000;
      margin: 8px 0;
    }}
    .double-divider {{
      border-top: 2px solid #000;
      margin: 8px 0;
    }}
    .order-header {{
      display: flex;
      justify-content: space-between;
      font-size: 12px;
      margin-bottom: 4px;
    }}
    .cod-box {{
      border: 2px solid #000;
      padding: 8px;
      text-align: center;
      margin: 8px 0;
      background: #f8fafc;
    }}
    .cod-title {{
      font-size: 11px;
      font-weight: bold;
      text-transform: uppercase;
    }}
    .cod-amount {{
      font-size: 20px;
      font-weight: 900;
    }}
    .section-title {{
      font-size: 11px;
      text-transform: uppercase;
      font-weight: bold;
      text-decoration: underline;
      margin-top: 6px;
      margin-bottom: 4px;
    }}
    .info-row {{
      font-size: 11px;
      line-height: 1.4;
      margin-bottom: 3px;
    }}
    .info-label {{
      font-weight: bold;
      display: inline-block;
      width: 75px;
    }}
    .item-desc {{
      font-size: 12px;
      font-weight: bold;
      margin: 4px 0;
    }}
    .notes-box {{
      font-size: 10px;
      font-style: italic;
      color: #334155;
      margin-top: 4px;
      background: #f8fafc;
      padding: 4px;
      border-left: 2px solid #000;
    }}
    .barcode-placeholder {{
      text-align: center;
      margin-top: 10px;
      letter-spacing: 5px;
      font-size: 14px;
      font-weight: bold;
    }}
    .print-btn-bar {{
      position: fixed;
      bottom: 20px;
      right: 20px;
      z-index: 100;
    }}
    .btn {{
      background: #0f172a;
      color: white;
      padding: 10px 18px;
      border: none;
      border-radius: 8px;
      font-weight: bold;
      cursor: pointer;
      font-family: sans-serif;
      box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    }}
    @media print {{
      body {{
        background: transparent;
        padding: 0;
      }}
      .slip {{
        box-shadow: none;
        border: none;
        width: 100%;
        padding: 0;
      }}
      .print-btn-bar {{
        display: none;
      }}
    }}
  </style>
</head>
<body>

  <div class="slip">
    <div class="text-center">
      <div class="title">{settings.STORE_NAME}</div>
      <div class="subtitle">{settings.STORE_TAGLINE}</div>
      <div class="subtitle">Helpline: {settings.STORE_CONTACT}</div>
    </div>

    <div class="double-divider"></div>

    <div class="order-header">
      <span><strong>ORDER #:</strong> {order.order_code}</span>
      <span>{order.created_at[:10]}</span>
    </div>

    <!-- COD Box -->
    <div class="cod-box">
      <div class="cod-title">{order.payment_method.upper()}</div>
      <div class="cod-amount">{cod_highlight}</div>
    </div>

    <!-- Receiver Details -->
    <div class="section-title">DELIVERY DETAILS</div>
    <div class="info-row">
      <span class="info-label">Customer:</span> <strong>{order.customer_name}</strong>
    </div>
    <div class="info-row">
      <span class="info-label">Primary:</span> <strong>{order.phone_primary}</strong>
    </div>
    {f'<div class="info-row"><span class="info-label">Alt Phone:</span> <strong>{order.phone_secondary}</strong></div>' if order.phone_secondary else ''}
    <div class="info-row">
      <span class="info-label">City:</span> <strong>{order.city}</strong>
    </div>
    <div class="info-row">
      <span class="info-label">Address:</span> {order.address}, {order.area}
    </div>
    {f'<div class="info-row"><span class="info-label">Landmark:</span> {order.nearest_landmark}</div>' if order.nearest_landmark else ''}

    <div class="divider"></div>

    <!-- Item Details -->
    <div class="section-title">ITEM PARTICULARS</div>
    <div class="item-desc">
      ?? {order.shoe_brand_model}
    </div>
    <div class="info-row">
      <span class="info-label">Size:</span> <strong>{order.shoe_size}</strong>
    </div>
    {f'<div class="notes-box">Note: {order.notes}</div>' if order.notes else ''}

    <div class="divider"></div>

    <!-- Barcode / Slip ID -->
    <div class="barcode-placeholder">
      * {order.order_code} *
    </div>
    <div class="text-center" style="font-size: 9px; color: #64748b; margin-top: 6px;">
      Please inspect parcel upon delivery ? Thank you!
    </div>
  </div>

  <div class="print-btn-bar">
    <button class="btn" onclick="window.print()">??? Print Waybill</button>
  </div>

</body>
</html>"""


def save_invoice_file(order: Order) -> str:
    """Save the HTML slip to static directory and return relative path."""
    os.makedirs(settings.INVOICES_DIR, exist_ok=True)
    filename = f"{order.order_code}.html"
    filepath = settings.INVOICES_DIR / filename
    html_content = generate_thermal_invoice_html(order)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html_content)

    logger.info("invoice_saved", order_code=order.order_code, path=str(filepath))
    return f"/static/invoices/{filename}"

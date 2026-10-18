"""
Invoice and Dispatch Slip Generator for Thrifted Shoes.
Creates modern, clean, minimalist parcel dispatch slips matching the store's custom card design.
Supports single slip printing and interactive in-page Batch Printing (fits 4 invoices per A4 page on Default printer settings).
"""
from __future__ import annotations

import os
import html
import json
from pathlib import Path
from typing import Optional
from app.core.config import settings
from app.core.logging import get_logger
from app.models.order import Order

logger = get_logger(__name__)


def _escape(text: Optional[str]) -> str:
    """HTML escape string safely."""
    return html.escape(str(text or "").strip())


def render_slip_card_html(order: Order, hide_meta: bool = False) -> str:
    """
    Renders an individual minimalist dispatch slip card.
    Faithfully matches the client's reference design:
    - SHOE & SIZE header: Shoe name gets maximum room, SIZE is positioned in the right corner.
    - Clean horizontal divider
    - CUSTOMER NAME (large bold)
    - PHONE NUMBER (large bold)
    - CITY (bold)
    - ADDRESS (clear multiline text)
    - Subtle dashed divider
    - NOTES box (open bordered box for instructions/notes)
    - Subtle discrete slip ID/tracking footer
    """
    customer_name = _escape(order.customer_name)
    phone_primary = _escape(order.phone_primary)
    phone_secondary = _escape(order.phone_secondary)
    city = _escape(order.city)
    address = _escape(order.full_address or order.address)
    shoe_name = _escape(order.shoe_brand_model)
    shoe_size = _escape(order.shoe_size)
    notes = _escape(order.notes)
    order_code = _escape(order.order_code)
    payment_method = _escape(order.payment_method or "Cash on Delivery")
    price_fmt = f"PKR {order.price:,.0f}"

    secondary_html = f' <span class="alt-phone">({phone_secondary})</span>' if phone_secondary else ""
    notes_content = notes if notes else ""

    meta_footer_html = ""
    if not hide_meta:
        meta_footer_html = f"""
    <div class="card-meta-footer">
      <span class="meta-code">#{order_code}</span>
      <span class="meta-payment">{price_fmt} &bull; {payment_method}</span>
    </div>"""

    return f"""
    <div class="slip-card" data-order-code="{order_code}">
      <!-- Top SHOE & SIZE Header (Shoe gets full room, Size in right corner) -->
      <div class="card-top-header">
        <div class="header-col header-shoe">
          <div class="field-label">SHOE</div>
          <div class="field-value-line">
            <span class="header-val shoe-val">{shoe_name}</span>
            <div class="underline"></div>
          </div>
        </div>
        <div class="header-v-divider"></div>
        <div class="header-col header-size">
          <div class="field-label text-right">SIZE</div>
          <div class="field-value-line">
            <span class="header-val size-val text-right">{shoe_size}</span>
            <div class="underline"></div>
          </div>
        </div>
      </div>

      <div class="header-h-divider"></div>

      <!-- Customer & Delivery Details -->
      <div class="card-body">
        <div class="field-group">
          <div class="field-label">CUSTOMER NAME</div>
          <div class="field-val name-val">{customer_name}</div>
        </div>

        <div class="field-group">
          <div class="field-label">PHONE NUMBER</div>
          <div class="field-val phone-val">{phone_primary}{secondary_html}</div>
        </div>

        <div class="field-group">
          <div class="field-label">CITY</div>
          <div class="field-val city-val">{city}</div>
        </div>

        <div class="field-group address-group">
          <div class="field-label">ADDRESS</div>
          <div class="field-val address-val">{address}</div>
        </div>
      </div>

      <div class="dashed-divider"></div>

      <!-- Notes Section -->
      <div class="notes-section">
        <div class="field-label">NOTES</div>
        <div class="notes-box">{notes_content}</div>
      </div>
      {meta_footer_html}
    </div>
    """


def get_common_css() -> str:
    """
    Core typography and styling for dispatch slips.
    Uses simple, standard sans-serif font family and accurate layout metrics.
    Carefully calibrated so 4 cards fit cleanly on 1 A4 page under Chrome's Default margin settings.
    """
    return """
    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      -webkit-print-color-adjust: exact !important;
      print-color-adjust: exact !important;
    }

    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      background-color: #f1f5f9;
      color: #0b192c;
      -webkit-font-smoothing: antialiased;
    }

    /* ── Single Slip Card ── */
    .slip-card {
      background: #ffffff;
      border: 1.5px solid #cbd5e1;
      border-radius: 8px;
      padding: 10px 14px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      box-sizing: border-box;
      position: relative;
      overflow: hidden;
    }

    /* Top Header: SHOE (expanded) | SIZE (in right corner) */
    .card-top-header {
      display: flex;
      align-items: flex-end;
      width: 100%;
      gap: 10px;
    }

    .header-shoe {
      flex: 1;
      min-width: 0;
    }

    .header-size {
      flex: 0 0 auto;
      min-width: 65px;
      max-width: 95px;
      text-align: right;
    }

    .header-v-divider {
      width: 1.5px;
      background-color: #cbd5e1;
      align-self: stretch;
      margin-bottom: 2px;
      flex-shrink: 0;
    }

    .text-right {
      text-align: right !important;
    }

    .field-label {
      font-size: 9.5px;
      font-weight: 700;
      letter-spacing: 0.7px;
      text-transform: uppercase;
      color: #5b6b82;
      margin-bottom: 2px;
    }

    .field-value-line {
      display: flex;
      flex-direction: column;
    }

    .shoe-val {
      font-size: 13.5px;
      font-weight: 700;
      color: #0b192c;
      white-space: normal;
      word-break: break-word;
      line-height: 1.2;
      min-height: 18px;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }

    .size-val {
      font-size: 13.5px;
      font-weight: 700;
      color: #0b192c;
      white-space: nowrap;
      text-align: right;
      min-height: 18px;
    }

    .underline {
      height: 1.5px;
      background-color: #cbd5e1;
      width: 100%;
      margin-top: 3px;
    }

    .header-h-divider {
      height: 1.5px;
      background-color: #cbd5e1;
      width: 100%;
      margin: 7px 0 9px 0;
    }

    /* Customer details body */
    .card-body {
      display: flex;
      flex-direction: column;
      gap: 6px;
      flex-grow: 1;
    }

    .field-group {
      display: flex;
      flex-direction: column;
    }

    .name-val {
      font-size: 18px;
      font-weight: 800;
      color: #0b192c;
      letter-spacing: -0.2px;
      line-height: 1.15;
    }

    .phone-val {
      font-size: 18px;
      font-weight: 800;
      color: #0b192c;
      letter-spacing: 0.2px;
      line-height: 1.15;
    }

    .alt-phone {
      font-size: 12px;
      font-weight: 600;
      color: #64748b;
    }

    .city-val {
      font-size: 14px;
      font-weight: 700;
      color: #0b192c;
      line-height: 1.2;
    }

    .address-val {
      font-size: 12px;
      font-weight: 500;
      color: #0f172a;
      line-height: 1.3;
      word-break: break-word;
    }

    /* Dashed line */
    .dashed-divider {
      border-top: 1.5px dashed #cbd5e1;
      width: 100%;
      margin: 7px 0 7px 0;
    }

    /* Notes */
    .notes-section {
      display: flex;
      flex-direction: column;
      margin-bottom: 2px;
    }

    .notes-box {
      border: 1.5px solid #cbd5e1;
      border-radius: 6px;
      min-height: 38px;
      max-height: 52px;
      padding: 4px 8px;
      font-size: 11px;
      line-height: 1.3;
      color: #334155;
      background-color: #ffffff;
      word-break: break-word;
      white-space: pre-wrap;
      overflow: hidden;
    }

    /* Subtle slip footer */
    .card-meta-footer {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-top: 4px;
      font-size: 9px;
      color: #94a3b8;
      font-weight: 500;
      letter-spacing: 0.3px;
    }

    .meta-code {
      font-weight: 700;
      color: #64748b;
    }

    /* ── Action Toolbar (Screen Only) ── */
    .action-toolbar {
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      background: #0f172a;
      color: #ffffff;
      padding: 12px 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
      z-index: 1000;
    }

    .toolbar-title {
      font-size: 14px;
      font-weight: 700;
      letter-spacing: 0.3px;
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .toolbar-actions {
      display: flex;
      gap: 10px;
      align-items: center;
    }

    .btn {
      padding: 8px 16px;
      border-radius: 6px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      border: none;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.15s ease;
    }

    .btn-primary {
      background: #2563eb;
      color: #ffffff;
    }
    .btn-primary:hover {
      background: #1d4ed8;
    }

    .btn-batch {
      background: #0ea5e9;
      color: #ffffff;
    }
    .btn-batch:hover {
      background: #0284c7;
    }

    .btn-outline {
      background: transparent;
      color: #cbd5e1;
      border: 1px solid #475569;
    }
    .btn-outline:hover {
      background: #1e293b;
      color: #ffffff;
    }

    /* ── A4 Print Sheet Container (2x2 Grid) ── */
    .page-sheet {
      box-sizing: border-box;
      background: #ffffff;
      box-shadow: 0 4px 14px rgba(0,0,0,0.08);
      margin: 70px auto 30px auto;
      width: 210mm;
      max-width: 195mm;
      padding: 4mm;
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      grid-template-rows: repeat(2, 1fr);
      gap: 4mm 6mm;
    }

    /* Sizing for 4 cards per sheet */
    .page-sheet .slip-card {
      height: 118mm;
      max-height: 120mm;
      padding: 10px 12px;
    }

    .single-view-container {
      margin: 80px auto 40px auto;
      width: 100mm;
    }
    .single-view-container .slip-card {
      min-height: 125mm;
      padding: 16px 18px;
      box-shadow: 0 4px 16px rgba(0,0,0,0.06);
    }

    /* ── Batch Selection Modal ── */
    .modal-backdrop {
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(15, 23, 42, 0.65);
      backdrop-filter: blur(4px);
      z-index: 2000;
      align-items: center;
      justify-content: center;
      padding: 16px;
    }
    .modal-box {
      background: #ffffff;
      border-radius: 12px;
      width: 580px;
      max-width: 95vw;
      max-height: 88vh;
      display: flex;
      flex-direction: column;
      box-shadow: 0 20px 40px rgba(0,0,0,0.25);
      overflow: hidden;
      animation: modalFadeIn 0.2s ease-out;
    }
    @keyframes modalFadeIn {
      from { opacity: 0; transform: scale(0.96) translateY(-8px); }
      to { opacity: 1; transform: scale(1) translateY(0); }
    }
    .modal-header {
      padding: 16px 20px;
      background: #0f172a;
      color: #ffffff;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .modal-header-title {
      font-size: 16px;
      font-weight: 700;
    }
    .modal-header-sub {
      font-size: 12px;
      color: #94a3b8;
      margin-top: 2px;
    }
    .modal-close-btn {
      background: none;
      border: none;
      color: #cbd5e1;
      font-size: 24px;
      cursor: pointer;
      line-height: 1;
      padding: 4px;
    }
    .modal-close-btn:hover {
      color: #ffffff;
    }
    .modal-toolbar {
      padding: 12px 20px;
      background: #f8fafc;
      border-bottom: 1px solid #e2e8f0;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
    }
    .search-input {
      flex: 1;
      padding: 8px 12px;
      border: 1px solid #cbd5e1;
      border-radius: 6px;
      font-size: 13px;
      outline: none;
    }
    .search-input:focus {
      border-color: #2563eb;
    }
    .count-badge {
      background: #e0f2fe;
      color: #0369a1;
      padding: 6px 12px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      white-space: nowrap;
    }
    .count-badge.max-reached {
      background: #fef3c7;
      color: #b45309;
    }
    .modal-list {
      padding: 8px 12px;
      overflow-y: auto;
      max-height: 52vh;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .order-item-row {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 10px 12px;
      border: 1.5px solid #e2e8f0;
      border-radius: 8px;
      cursor: pointer;
      transition: all 0.15s ease;
      user-select: none;
    }
    .order-item-row:hover {
      background: #f8fafc;
      border-color: #cbd5e1;
    }
    .order-item-row.selected {
      background: #f0f9ff;
      border-color: #38bdf8;
    }
    .order-item-row.disabled {
      opacity: 0.55;
      cursor: not-allowed;
      background: #f8fafc;
    }
    .order-chk {
      width: 18px;
      height: 18px;
      cursor: pointer;
      accent-color: #0284c7;
    }
    .order-info {
      flex: 1;
      min-width: 0;
    }
    .order-code-badge {
      font-weight: 800;
      color: #0f172a;
      font-size: 13px;
    }
    .current-badge {
      background: #dbeafe;
      color: #1e40af;
      font-size: 10px;
      padding: 2px 6px;
      border-radius: 4px;
      font-weight: 700;
      margin-left: 6px;
      text-transform: uppercase;
    }
    .order-meta-line {
      font-size: 12px;
      color: #475569;
      margin-top: 2px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .modal-footer {
      padding: 14px 20px;
      background: #f8fafc;
      border-top: 1px solid #e2e8f0;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .footer-hint {
      font-size: 12px;
      color: #64748b;
    }

    /* ── @media print for flawless 4-per-page A4 printing (Works on Default Margins) ── */
    @page {
      size: A4 portrait;
      margin: 4mm 6mm;
    }

    @media print {
      html, body {
        background: transparent !important;
        padding: 0 !important;
        margin: 0 !important;
        width: 100% !important;
        height: 100% !important;
      }

      .no-print,
      .modal-backdrop,
      .action-toolbar {
        display: none !important;
      }

      .single-view-container {
        margin: 0 !important;
        width: 100% !important;
      }

      .single-view-container .slip-card {
        box-shadow: none !important;
        border: 1.5px solid #000 !important;
        width: 100% !important;
        max-width: 95mm !important;
        page-break-inside: avoid;
        break-inside: avoid;
      }

      .page-sheet {
        box-shadow: none !important;
        margin: 0 auto !important;
        width: 100% !important;
        max-width: 190mm !important;
        height: auto !important;
        max-height: 242mm !important;
        padding: 0 !important;
        display: grid !important;
        grid-template-columns: repeat(2, 1fr) !important;
        grid-template-rows: repeat(2, 1fr) !important;
        gap: 3mm 5mm !important;
        page-break-after: always !important;
        break-after: page !important;
        box-sizing: border-box !important;
      }

      .page-sheet:last-of-type {
        page-break-after: avoid !important;
        break-after: avoid !important;
      }

      .page-sheet .slip-card {
        height: 118mm !important;
        max-height: 119mm !important;
        box-sizing: border-box !important;
        page-break-inside: avoid !important;
        break-inside: avoid !important;
        border: 1.5px solid #cbd5e1 !important;
        padding: 9px 12px !important;
        overflow: hidden !important;
      }
    }
    """


def generate_single_invoice_page(
    order: Order,
    other_orders: Optional[list[Order]] = None,
    batch_orders: Optional[list[Order]] = None,
    layout: str = "single",
) -> str:
    """
    Renders the dispatch slip page.
    Includes:
    - Clean single slip view matching the client's reference design.
    - Shoe name given maximum room, with Size positioned cleanly in right corner.
    - In-page 'Batch Printing' option: pre-selects 4 invoices by default,
      allowing the owner to adjust or print 4 invoices together on 1 A4 page under Default printer margins.
    """
    css = get_common_css()

    # Pre-render cards for all candidate orders
    candidates: dict[str, Order] = {order.order_code: order}
    if other_orders:
        for o in other_orders:
            if o.order_code not in candidates:
                candidates[o.order_code] = o

    # If explicit batch_orders are requested to view directly
    initial_batch_mode = bool(batch_orders and len(batch_orders) > 1)
    if initial_batch_mode:
        for bo in batch_orders:
            candidates[bo.order_code] = bo

    # Serialize orders data to JSON for client-side selection
    cards_html_map = {code: render_slip_card_html(o) for code, o in candidates.items()}
    orders_json_str = json.dumps(cards_html_map)

    # Build modal rows
    rows_html = []
    # Ensure current order is first in the list
    ordered_list = [order] + [o for o in candidates.values() if o.order_code != order.order_code]

    # Default settings: pre-select up to 4 invoices by default so 4 are ready to print immediately
    for idx, o in enumerate(ordered_list):
        is_curr = (o.order_code == order.order_code)
        if initial_batch_mode and batch_orders:
            initially_checked = any(bo.order_code == o.order_code for bo in batch_orders)
        else:
            # Pre-select top 4 by default
            initially_checked = (idx < 4)

        checked_attr = "checked" if initially_checked else ""
        selected_class = "selected" if initially_checked else ""
        curr_badge = '<span class="current-badge">Current</span>' if is_curr else ""

        rows_html.append(f"""
        <label class="order-item-row {selected_class}" id="row_{o.order_code}" onclick="handleRowClick(event, '{o.order_code}')">
          <input type="checkbox" class="order-chk" value="{o.order_code}" {checked_attr} onchange="onCheckboxChange(this)">
          <div class="order-info">
            <div>
              <span class="order-code-badge">#{o.order_code}</span>{curr_badge}
              <strong style="margin-left: 6px; color:#0f172a;">{_escape(o.customer_name)}</strong>
              <span style="color:#64748b; font-size:12px;">({_escape(o.city)})</span>
            </div>
            <div class="order-meta-line">
              👟 {_escape(o.shoe_brand_model)} &bull; Size: {_escape(o.shoe_size)} &bull; PKR {o.price:,.0f}
            </div>
          </div>
        </label>
        """)

    modal_items_html = "\n".join(rows_html)

    # Single slip card
    single_card_html = render_slip_card_html(order)

    # If batch mode was directly requested in URL
    if initial_batch_mode and batch_orders:
        batch_cards = "".join([render_slip_card_html(bo) for bo in batch_orders[:4]])
        batch_sheet_html = f'<div class="page-sheet" id="printSheet">{batch_cards}</div>'
        single_display = "none"
        batch_display = "block"
        toolbar_state_text = f"📑 Batch Print ({len(batch_orders[:4])} Invoices on 1 Page)"
    else:
        batch_sheet_html = '<div class="page-sheet" id="printSheet" style="display:none;"></div>'
        single_display = "block"
        batch_display = "none"
        toolbar_state_text = f"📦 Slip #{order.order_code} &bull; {_escape(order.customer_name)}"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Dispatch Slip - {order.order_code}</title>
  <style>{css}</style>
</head>
<body>
  <!-- Action Toolbar (Hidden when printing) -->
  <div class="action-toolbar no-print">
    <div class="toolbar-title" id="toolbarTitle">
      {toolbar_state_text}
    </div>
    <div class="toolbar-actions">
      <button class="btn btn-primary" onclick="triggerPrint()">
        🖨️ Print
      </button>
      <button class="btn btn-batch" id="batchBtn" onclick="openBatchModal()">
        📑 Batch Printing (Select up to 4)
      </button>
      <button class="btn btn-outline" id="singleViewBtn" onclick="switchToSingleView()" style="display:{'inline-flex' if initial_batch_mode else 'none'};">
        ↩ Single Slip View
      </button>
    </div>
  </div>

  <!-- Single Slip View Container -->
  <div class="single-view-container" id="singleContainer" style="display:{single_display};">
    {single_card_html}
  </div>

  <!-- Batch 4-Up A4 Print Sheet Container -->
  <div id="batchContainer" style="display:{batch_display};">
    {batch_sheet_html}
  </div>

  <!-- Batch Printing Selection Modal -->
  <div class="modal-backdrop no-print" id="batchModal" onclick="onBackdropClick(event)">
    <div class="modal-box">
      <div class="modal-header">
        <div>
          <div class="modal-header-title">📑 Batch Printing (1 Page)</div>
          <div class="modal-header-sub">Select up to 4 invoices to print together in a 2×2 grid on a single A4 page.</div>
        </div>
        <button class="modal-close-btn" onclick="closeBatchModal()">&times;</button>
      </div>

      <div class="modal-toolbar">
        <input type="text" class="search-input" id="orderSearch" placeholder="🔍 Search customer name, phone, city, or order #..." oninput="filterOrders()">
        <span class="count-badge" id="countBadge">4 / 4 selected</span>
      </div>

      <div class="modal-list" id="modalOrderList">
        {modal_items_html}
      </div>

      <div class="modal-footer">
        <div class="footer-hint" id="footerHint">
          Select up to 4 invoices (fits on 1 single A4 page with default margins).
        </div>
        <div style="display:flex;gap:8px;">
          <button class="btn btn-outline" style="color:#0f172a;border-color:#cbd5e1;" onclick="closeBatchModal()">Cancel</button>
          <button class="btn btn-primary" id="confirmBatchBtn" onclick="applyBatchSelection()">
            🖨️ Print Selected Invoices
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- Pre-loaded slip card templates -->
  <script>
    const CARDS_MAP = {orders_json_str};
    const CURRENT_CODE = "{order.order_code}";
    const MAX_ALLOWED = 4;

    function openBatchModal() {{
      updateSelectionUI();
      document.getElementById('batchModal').style.display = 'flex';
      document.getElementById('orderSearch').value = '';
      filterOrders();
    }}

    function closeBatchModal() {{
      document.getElementById('batchModal').style.display = 'none';
    }}

    function onBackdropClick(e) {{
      if (e.target.id === 'batchModal') {{
        closeBatchModal();
      }}
    }}

    function handleRowClick(e, code) {{
      if (e.target.tagName === 'INPUT') return;
      const chk = document.querySelector(`.order-chk[value="${{code}}"]`);
      if (chk) {{
        if (!chk.checked && getSelectedCodes().length >= MAX_ALLOWED) {{
          showMaxAlert();
          return;
        }}
        chk.checked = !chk.checked;
        onCheckboxChange(chk);
      }}
    }}

    function onCheckboxChange(chk) {{
      const selected = getSelectedCodes();
      if (selected.length > MAX_ALLOWED) {{
        chk.checked = false;
        showMaxAlert();
        return;
      }}
      updateSelectionUI();
    }}

    function getSelectedCodes() {{
      return Array.from(document.querySelectorAll('.order-chk:checked')).map(c => c.value);
    }}

    function showMaxAlert() {{
      const hint = document.getElementById('footerHint');
      hint.style.color = '#dc2626';
      hint.innerText = '⚠️ Maximum 4 invoices can fit on 1 A4 page. Uncheck one to pick another.';
      setTimeout(() => {{
        hint.style.color = '#64748b';
        hint.innerText = 'Select up to 4 invoices (fits on 1 single A4 page with default margins).';
      }}, 3000);
    }}

    function updateSelectionUI() {{
      const selected = getSelectedCodes();
      const count = selected.length;
      const badge = document.getElementById('countBadge');
      badge.innerText = `${{count}} / ${{MAX_ALLOWED}} selected`;

      if (count >= MAX_ALLOWED) {{
        badge.classList.add('max-reached');
      }} else {{
        badge.classList.remove('max-reached');
      }}

      // Update row active state and disable unchecked if max reached
      document.querySelectorAll('.order-item-row').forEach(row => {{
        const chk = row.querySelector('.order-chk');
        if (chk.checked) {{
          row.classList.add('selected');
          row.classList.remove('disabled');
          chk.disabled = false;
        }} else {{
          row.classList.remove('selected');
          if (count >= MAX_ALLOWED) {{
            row.classList.add('disabled');
            chk.disabled = true;
          }} else {{
            row.classList.remove('disabled');
            chk.disabled = false;
          }}
        }}
      }});
    }}

    function filterOrders() {{
      const query = document.getElementById('orderSearch').value.toLowerCase().trim();
      document.querySelectorAll('.order-item-row').forEach(row => {{
        const text = row.innerText.toLowerCase();
        row.style.display = text.includes(query) ? 'flex' : 'none';
      }});
    }}

    function applyBatchSelection() {{
      const selectedCodes = getSelectedCodes();
      if (selectedCodes.length === 0) {{
        alert('Please select at least 1 invoice.');
        return;
      }}

      closeBatchModal();

      // If only 1 selected and it's the current one, show single view
      if (selectedCodes.length === 1 && selectedCodes[0] === CURRENT_CODE) {{
        switchToSingleView();
        window.print();
        return;
      }}

      // Build 4-up grid inside batchContainer
      const cardsHtml = selectedCodes.map(code => CARDS_MAP[code] || '').join('');
      const batchContainer = document.getElementById('batchContainer');
      batchContainer.innerHTML = `<div class="page-sheet" id="printSheet">${{cardsHtml}}</div>`;

      // Toggle views
      document.getElementById('singleContainer').style.display = 'none';
      batchContainer.style.display = 'block';
      document.getElementById('singleViewBtn').style.display = 'inline-flex';
      document.getElementById('toolbarTitle').innerText = `📑 Batch Print (${{selectedCodes.length}} Invoices on 1 Page)`;

      // Auto trigger print
      setTimeout(() => {{
        window.print();
      }}, 150);
    }}

    function switchToSingleView() {{
      document.getElementById('batchContainer').style.display = 'none';
      document.getElementById('singleContainer').style.display = 'block';
      document.getElementById('singleViewBtn').style.display = 'none';
      document.getElementById('toolbarTitle').innerText = `📦 Slip #${{CURRENT_CODE}} &bull; {_escape(order.customer_name)}`;
    }}

    function triggerPrint() {{
      window.print();
    }}

    // Close on Escape
    window.addEventListener('keydown', (e) => {{
      if (e.key === 'Escape') {{
        closeBatchModal();
      }}
    }});

    // Initialize UI on load
    document.addEventListener('DOMContentLoaded', () => {{
      updateSelectionUI();
    }});
  </script>
</body>
</html>"""


def generate_batch_invoices_page(
    orders: list[Order],
    title: str = "Dispatch Slips Batch Print",
) -> str:
    """
    Renders a multi-order batch printing sheet that packs orders 4-per-page on A4 paper.
    Used for standalone batch links.
    """
    css = get_common_css()

    sheets_html = []
    chunk_size = 4
    for i in range(0, max(len(orders), 1), chunk_size):
        chunk = orders[i : i + chunk_size]
        cards = "".join([render_slip_card_html(o) for o in chunk])
        sheets_html.append(f'<div class="page-sheet">{cards}</div>')

    rendered_sheets = "\n".join(sheets_html) if orders else """
    <div class="single-view-container">
      <div style="background:#fff;padding:30px;border-radius:8px;text-align:center;color:#64748b;">
        <h3>No orders found to print.</h3>
      </div>
    </div>
    """

    total_orders = len(orders)
    total_sheets = (total_orders + 3) // 4 if total_orders else 0

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} (4 per A4 Page)</title>
  <style>{css}</style>
</head>
<body>
  <div class="action-toolbar no-print">
    <div class="toolbar-title">
      📑 Batch Dispatch Printing ({total_orders} slips &bull; {total_sheets} A4 Page{'s' if total_sheets != 1 else ''})
    </div>
    <div class="toolbar-actions">
      <button class="btn btn-primary" onclick="window.print()">
        🖨️ Print (4 Per Page)
      </button>
    </div>
  </div>

  <div id="sheetsContainer">
    {rendered_sheets}
  </div>
</body>
</html>"""


def generate_thermal_invoice_html(order: Order) -> str:
    """
    Backwards-compatible entrypoint.
    Renders the modern, clean slip matching the customer's desired layout.
    """
    return generate_single_invoice_page(order)


def save_invoice_file(order: Order) -> str:
    """Save the HTML slip to static directory and return relative path."""
    os.makedirs(settings.INVOICES_DIR, exist_ok=True)
    filename = f"{order.order_code}.html"
    filepath = settings.INVOICES_DIR / filename
    html_content = generate_single_invoice_page(order)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html_content)

    logger.info("invoice_saved", order_code=order.order_code, path=str(filepath))
    return f"/static/invoices/{filename}"

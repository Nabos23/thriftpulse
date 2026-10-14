"""
Automated diagnostics and end-to-end integration test runner.
"""
import asyncio
import os
import io
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import init_db, insert_order, search_orders, get_order_by_code
from app.services.invoice_generator import save_invoice_file, generate_thermal_invoice_html
from app.services.ai_assistant import process_owner_query
from main import app


def test_end_to_end():
    print("=" * 60)
    print("🏃 RUNNING END-TO-END SYSTEM INTEGRATION TESTS")
    print("=" * 60)

    # 1. Database Init
    print("\n[1/5] Testing Database Initialization...")
    init_db()
    print("✓ SQLite database and indexes initialized successfully.")

    # 2. Insert Test Order
    print("\n[2/5] Testing Order Creation in DB...")
    test_order_data = {
        "customer_name": "Ali Khan",
        "phone_primary": "03129214688",
        "phone_secondary": "03001234567",
        "city": "Lahore",
        "area": "Gulberg III",
        "address": "House 42, Street 8",
        "nearest_landmark": "Near Main Market",
        "shoe_brand_model": "Nike Air Jordan 1 Low",
        "shoe_size": "42 EU / 8.5 US",
        "price": 4800.0,
        "payment_method": "Cash on Delivery",
        "notes": "Please call before arriving",
        "shoe_image_path": "/static/uploads/shoes/test_shoe.jpg",
        "status": "Pending",
    }

    order = asyncio.run(insert_order(test_order_data))
    print(f"✓ Order created: Code={order.order_code}, Customer={order.customer_name}, ID={order.id}")

    # 3. Invoice Generation
    print("\n[3/5] Testing Thermal Invoice Slip Generation...")
    invoice_path = save_invoice_file(order)
    full_invoice_path = Path("app") / invoice_path.lstrip("/")
    assert full_invoice_path.exists(), f"Invoice file {full_invoice_path} does not exist!"
    print(f"✓ 80mm Thermal Waybill saved: {invoice_path} ({full_invoice_path.stat().st_size} bytes)")

    # 4. Search and Query
    print("\n[4/5] Testing Multi-Field Search (Name, Phone, Shoe)...")
    results_name = asyncio.run(search_orders("Ali"))
    print(f"✓ Search by Name 'Ali': found {len(results_name)} order(s)")
    assert len(results_name) >= 1

    results_phone = asyncio.run(search_orders("03129214688"))
    print(f"✓ Search by Phone '03129214688': found {len(results_phone)} order(s)")
    assert len(results_phone) >= 1

    results_shoe = asyncio.run(search_orders("Jordan"))
    print(f"✓ Search by Shoe 'Jordan': found {len(results_shoe)} order(s)")
    assert len(results_shoe) >= 1

    # 5. FastAPI HTTP Client Tests
    print("\n[5/5] Testing FastAPI Web Endpoints...")
    client = TestClient(app)

    # GET /order
    resp_form = client.get("/order")
    assert resp_form.status_code == 200
    assert "Delivery & Order Form" in resp_form.text
    print("✓ GET /order served successfully with 200 OK")

    # GET /webhook verification
    resp_webhook = client.get(f"/webhook?hub.mode=subscribe&hub.verify_token={settings.WHATSAPP_VERIFY_TOKEN}&hub.challenge=test_challenge_123")
    assert resp_webhook.status_code == 200
    assert resp_webhook.text == "test_challenge_123"
    print("✓ GET /webhook challenge verified with 200 OK")

    # GET /invoice/{order_code}
    resp_inv = client.get(f"/invoice/{order.order_code}")
    assert resp_inv.status_code == 200
    assert order.order_code in resp_inv.text
    print(f"✓ GET /invoice/{order.order_code} served successfully with 200 OK")

    # POST /api/orders with dummy image
    dummy_image = io.BytesIO(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb\x00C\x00")
    dummy_image.name = "sneaker.jpg"

    post_data = {
        "customer_name": "Usman Tariq",
        "phone_primary": "03219876543",
        "city": "Karachi",
        "area": "DHA Phase 6",
        "address": "Bungalow 12-B",
        "shoe_brand_model": "Adidas Forum Low White",
        "shoe_size": "43 EU",
        "price": "5200",
        "payment_method": "Cash on Delivery",
    }

    resp_order = client.post(
        "/api/orders",
        data=post_data,
        files={"shoe_photo": ("sneaker.jpg", dummy_image, "image/jpeg")},
    )
    assert resp_order.status_code == 200
    order_json = resp_order.json()
    assert order_json.get("status") == "ok"
    new_code = order_json["order"]["order_code"]
    print(f"✓ POST /api/orders submitted and processed! New Order Code: {new_code}")

    print("\n" + "=" * 60)
    print("🎉 ALL INTEGRATION TESTS PASSED PERFECTLY!")
    print("=" * 60)


if __name__ == "__main__":
    test_end_to_end()

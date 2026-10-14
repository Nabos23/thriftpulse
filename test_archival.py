"""
Test suite for archival service and maintenance shrink route.
"""
import sys
from pathlib import Path
from PIL import Image

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from fastapi.testclient import TestClient
from main import app
from app.services.archival import shrink_image_file, shrink_invoice_file, shrink_old_records


def test_archival():
    print("=" * 60)
    print("Testing Archival Service & Route (Option 3)")
    print("=" * 60)

    scratch_dir = Path("scratch")
    scratch_dir.mkdir(parents=True, exist_ok=True)

    # 1. Test image shrinking
    print("\n[1/4] Testing Image Shrinking...")
    test_img_path = scratch_dir / "test_orig_shoe.jpg"
    img = Image.new("RGB", (600, 400), color=(73, 109, 137))
    img.save(test_img_path, format="JPEG", quality=95)
    orig_sz = test_img_path.stat().st_size
    print(f"Original test image size: {orig_sz} bytes, 600x400")

    res = shrink_image_file(test_img_path, max_dimension=160, quality=50)
    new_sz = test_img_path.stat().st_size
    print(f"Shrunk test image: {res.get('status')}, size: {new_sz} bytes (saved {res.get('saved_bytes')} bytes)")
    assert res.get("status") == "shrunk"
    assert new_sz < orig_sz
    assert new_sz < 3000

    # Test idempotency (calling again on already shrunk image)
    res_again = shrink_image_file(test_img_path, max_dimension=160, quality=50)
    print(f"Second call status: {res_again.get('status')}")
    assert res_again.get("status") == "already_shrunk"
    print("✓ Image shrinking and idempotency verified!")

    # 2. Test invoice shrinking
    print("\n[2/4] Testing Invoice HTML Shrinking...")
    test_inv_path = scratch_dir / "test_invoice.html"
    sample_inv_file = Path("app/static/invoices/TS-1001.html")
    if sample_inv_file.exists():
        sample_invoice = sample_inv_file.read_text(encoding="utf-8")
    else:
        sample_invoice = """<!DOCTYPE html><html><head><style>""" + ("body { margin: 0; padding: 20px; font-family: sans-serif; }\n" * 50) + """</style></head><body><div class="slip">Test</div></body></html>"""
    test_inv_path.write_text(sample_invoice, encoding="utf-8")
    orig_inv_sz = test_inv_path.stat().st_size
    print(f"Original test invoice size: {orig_inv_sz} bytes")

    inv_res = shrink_invoice_file(test_inv_path)
    new_inv_sz = test_inv_path.stat().st_size
    print(f"Shrunk test invoice: {inv_res.get('status')}, size: {new_inv_sz} bytes (saved {inv_res.get('saved_bytes')} bytes)")
    assert inv_res.get("status") == "shrunk"
    assert new_inv_sz < orig_inv_sz
    assert "<!-- ARCHIVED_COMPACT -->" in test_inv_path.read_text(encoding="utf-8")

    # Test idempotency
    inv_again = shrink_invoice_file(test_inv_path)
    print(f"Second call status: {inv_again.get('status')}")
    assert inv_again.get("status") == "already_shrunk"
    print("✓ Invoice shrinking and idempotency verified!")

    # 3. Test batch cleanup function
    print("\n[3/4] Testing Batch Archival Function...")
    # Test dry_run=True with days=0 (match all current files)
    dry_res = shrink_old_records(days=0, dry_run=True)
    assert dry_res.get("status") == "ok"
    assert dry_res.get("dry_run") is True
    print(f"Dry run summary on all files (days=0): {dry_res['summary']}")

    # 4. Test FastAPI endpoints
    print("\n[4/4] Testing FastAPI /api/maintenance/shrink Endpoints...")
    client = TestClient(app)

    # GET dry_run=True (default days=90)
    resp_get = client.get("/api/maintenance/shrink?days=90&dry_run=true")
    assert resp_get.status_code == 200
    data_get = resp_get.json()
    assert data_get.get("status") == "ok"
    assert data_get.get("cutoff_days") == 90
    print("✓ GET /api/maintenance/shrink verified (200 OK)")

    # POST dry_run=True
    resp_post = client.post("/api/maintenance/shrink?days=90&dry_run=true")
    assert resp_post.status_code == 200
    data_post = resp_post.json()
    assert data_post.get("status") == "ok"
    print("✓ POST /api/maintenance/shrink verified (200 OK)")

    # Test alias route /api/index/maintenance/shrink
    resp_alias = client.get("/api/index/maintenance/shrink?days=90&dry_run=true")
    assert resp_alias.status_code == 200
    print("✓ GET /api/index/maintenance/shrink alias verified (200 OK)")

    print("\n" + "=" * 60)
    print("ALL ARCHIVAL & STORAGE SHRINK TESTS PASSED PERFECTLY!")
    print("=" * 60)


if __name__ == "__main__":
    test_archival()

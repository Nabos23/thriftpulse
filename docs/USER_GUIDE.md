# Thrifted Shoes Assistant - Complete User & Operation Guide

Welcome to the **Thrifted Shoes Assistant & Invoicing System**! This document provides an end-to-end operational guide for how the system works, how to run it, and how to interact with it.

---

## 1. Quick Start

### Starting the Server
From the project directory (`C:\claude`), start the server:
```bash
python main.py
```
The server will start on `http://0.0.0.0:8000`.

---

## 2. Customer Order Workflow

### A. The Public Order Link
Whenever a customer shows interest in a pair of thrifted shoes (on WhatsApp, Instagram DM, or Facebook), send them the standard public order link:
```
https://<your-domain-or-ngrok>/order
```
*(or simply `https://<your-domain-or-ngrok>/`)*

### B. What the Customer Experiences
1. **Shoe Details:**
   - **Shoe Photo Upload:** Customer attaches a photo/screenshot of the shoes. The webpage automatically compresses the image in the browser (down to ~300KB) so it uploads instantaneously even on 3G/4G.
   - **Shoe Article / Name:** e.g. *Nike Dunk Low Retro*
   - **Shoe Size:** e.g. *42 EU / 8.5 US*
   - **Agreed Price (PKR):** e.g. *4500*
   - **Payment Method:** Cash on Delivery (COD) or Bank Transfer
2. **Customer Contact & Delivery:**
   - Full Name
   - Primary Phone / WhatsApp (mandatory) & Alternate Phone (recommended for couriers)
   - City & Area (Sector / Colony)
   - House / Street / Flat details
   - Prominent nearby landmark
3. **Instant Confirmation:**
   - Upon tapping **"Confirm & Place Order"**, the order is assigned an ID (e.g. `TS-1001`), logged in the local database, synced to the **"Orders"** tab in your Google Sheet, and the thermal waybill is generated.

---

## 3. Owner Automated Alerts & Thermal Invoice Printing

As soon as an order is submitted:
1. **WhatsApp Alert Sent to Owner:**
   - The bot sends a message to the owner's WhatsApp number with all customer details and a 1-tap link to view/print the shipping slip.
   - The bot immediately sends the **photo of the shoes** to the owner so they know exactly which pair to pack.
2. **80mm Thermal Waybill Slip:**
   - Accessible at `https://<your-domain>/invoice/TS-1001`.
   - Formatted specifically for 80mm portable Bluetooth thermal receipt printers or standard A4 printers.
   - Shows bold order number, COD amount, customer contact, delivery address, and shoe size.

---

## 4. Owner Multilingual WhatsApp AI Assistant

When the owner messages the WhatsApp bot from their phone, they can ask questions in **English**, **Roman Urdu / Hindi**, **Urdu Script**, or send a **Voice Note**:

### Example Interactions

| Query Format | Example Message | What the Bot Does |
| :--- | :--- | :--- |
| **Name Query** | *"Ali k joote ki details aur picture bhejo"* | Looks up Ali's order, returns name, phone, address, COD amount, and sends the shoe image into the chat. |
| **Phone Query** | *"03129214688 kis ka order hai?"* | Instantly returns the customer name, order code, and delivery status. |
| **Shoe Query** | *"Jordan kis ne li thi?"* | Finds orders containing "Jordan" and provides delivery status. |
| **Ambiguous Query** | *"Ali ka status kya hai?"* (if multiple Alis exist) | Replies with a clean disambiguation list: `1. Ali Khan (Lahore) 2. Ali Raza (Karachi)`. Reply with `1` or `2` to get full card + photo. |
| **Voice Note (Audio)** | Owner sends a voice note: *"Ali ka phone number aur address kya hai?"* | The bot downloads the audio, transcribes with **OpenAI Whisper**, and replies with Ali's contact and address. |
| **Recent Orders** | *"Last 5 orders dikhao"* | Lists the 5 most recent orders with summary and status. |

---

## 5. Architecture & File Structure

```
c:\claude\
├── .env                       # API keys, tokens, and configuration
├── google_token.json          # Cached Google OAuth token
├── google_credentials.json    # Google OAuth credentials
├── thrift_orders.db           # Zero-config SQLite database (WAL mode)
├── main.py                    # FastAPI application entry point
├── test_runner.py             # Integration test runner
├── docs/                      # Architecture and edge-case documentation
├── app/
│   ├── api/
│   │   └── orders.py          # /order, /api/orders, /invoice routes
│   ├── connectors/
│   │   ├── google_sheets.py   # Live Google Sheets sync
│   │   └── whatsapp_client.py # Meta WhatsApp Cloud API client
│   ├── core/
│   │   ├── config.py          # Pydantic settings
│   │   ├── database.py        # SQLite database operations
│   │   └── logging.py         # Structlog logger
│   ├── models/
│   │   └── order.py           # Pydantic order schemas
│   ├── services/
│   │   ├── ai_assistant.py    # Multilingual OpenRouter / OpenAI query engine
│   │   ├── invoice_generator.py# 80mm thermal waybill generator
│   │   └── voice.py           # Multi-Engine Whisper (Groq Free Cloud / Local faster-whisper)
│   ├── static/
│   │   ├── invoices/          # Generated HTML shipping slips
│   │   └── uploads/shoes/     # Compressed shoe images
│   └── templates/
│       └── order_form.html    # Premium responsive order form
```

---

## 7. OpenRouter & Whisper Setup (100% Free Tier Setup)

### A. OpenRouter for AI Queries & Tool Search
Set in `.env`:
```ini
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=your_openrouter_api_key
DEFAULT_MODEL=openrouter/free
```
- `openrouter/free` automatically routes your queries to active free open-source models supporting function/tool calling.
- You can also choose specific free models, e.g.:
  - `meta-llama/llama-3.3-70b-instruct:free`
  - `google/gemini-2.0-flash-exp:free`
  - `qwen/qwen-2.5-72b-instruct:free`

### B. Dealing with Whisper Audio Transcription (Free Tier)
Because OpenRouter free models do not include audio transcription, the system supports an **intelligent auto-detection cascade**:

1. **Option 1: Groq Free Whisper Cloud (Recommended)**
   - Groq provides `whisper-large-v3-turbo` completely **free** with no credit card required.
   - Simply get a free API key at [console.groq.com](https://console.groq.com) and add:
     ```ini
     GROQ_API_KEY=gsk_...
     ```
   - Voice notes transcribe in ~300ms.

2. **Option 2: 100% Local Whisper (Offline / Zero Cost)**
   - Powered by `faster-whisper`.
   - If no Groq key is supplied, the bot automatically transcribes voice notes locally on your CPU/GPU without needing any API key or internet access.


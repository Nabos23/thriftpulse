# ThriftBot: Order & Invoicing System with WhatsApp AI Assistant

## 1. Project Overview & Business Context
**Business Model:** Thrifted Shoes (1-of-1 unique inventory items, cleaned, photographed, and posted on Instagram/WhatsApp groups).
**Core Challenge:** Manual Excel-based order tracking leads to lost customer info, inability to access customer contact details and shoe photos on-the-go (e.g. when couriers/riders call for directions), and slow manual invoice preparation.

---

## 2. System Architecture

```
                       +---------------------------------------------+
                       |             Customer Touchpoint             |
                       |  - Customer messages seller on WhatsApp/IG  |
                       |  - Seller sends standard public order link  |
                       |    (e.g., mysite.com/order)                 |
                       +---------------------------------------------+
                                              |
                                              v
                       +---------------------------------------------+
                       |         Fast Mobile-First Web Form          |
                       |  - Static public form for all customers     |
                       |  - Customer Name & 2 Phone Numbers          |
                       |  - Complete Delivery Address & City         |
                       |  - Shoe Photo Upload (compressed on client) |
                       |  - Shoe Size, Article/Brand & Agreed Price  |
                       |  - Payment Method (COD / Bank Transfer)     |
                       |  - "Submit Order" button -> POST /api/order |
                       +---------------------------------------------+
                                              |
                                              v
                                   [ FastAPI Backend ]
                                              |
                     +------------------------+------------------------+
                     |                        |                        |
                     v                        v                        v
            +-----------------+      +-----------------+      +-----------------+
            | SQLite Database |      |  Google Sheets  |      | Media & Invoice |
            |  (Primary Truth)|      |  (Live Backup)  |      |    Storage      |
            +-----------------+      +-----------------+      +-----------------+
                     |                                                 |
                     +------------------------+------------------------+
                                              |
                                              v
                       +---------------------------------------------+
                       |           Order Trigger & Dispatch          |
                       |  - Generates Printable Waybill/Invoice(PDF) |
                       |  - Sends WhatsApp Notification + Invoice    |
                       |    directly to Owner's WhatsApp number      |
                       +---------------------------------------------+
                                              |
                                              v
                       +---------------------------------------------+
                       |     Owner Multilingual WhatsApp Assistant   |
                       |  - Modalities: English, Urdu, Roman Urdu    |
                       |    AND Voice Notes (Whisper STT transcription)|
                       |  - Examples:                                |
                       |    * "Ali k joote ki picture aur address do"|
                       |    * "Details about Ali"                    |
                       |    * [Voice Note]: "Ali ka number kya hai?" |
                       |  - Queries DB via tool calling              |
                       |  - Dispatches formatted details + original  |
                       |    shoe image directly back to owner!       |
                       +---------------------------------------------+
```

---

## 3. Technology Stack (Inherited & Adapted from RentDesk)
- **Backend Framework:** FastAPI (Python 3.12+)
- **Database:** SQLite (SQLAlchemy / SQLModel / aiosqlite) for instant, local, zero-latency queries.
- **Google Sheets Sync:** Google Sheets API v4 (Service Account or OAuth2 token).
- **WhatsApp Integration:** Meta WhatsApp Cloud API v20.0+ (Outbound messages, templates, inbound webhook, media upload/download).
- **AI Engine:** OpenAI GPT-4o / GPT-4o-mini with Tool Calling / Structured Outputs.
- **Invoice Generation:** ReportLab / WeasyPrint / HTML-to-Image for clean 80mm thermal shipping labels or A4 invoices.
- **Frontend Form:** Lightweight, modern responsive web form with automatic client-side image compression.

---

## 4. Key Constraints & Critical Flaws Identified

### A. Meta WhatsApp Cloud API Constraints
1. **24-Hour Messaging Window:**
   - Meta strictly enforces a 24-hour customer service window for free-form messages.
   - *Solution:* The bot communicates with the **Owner**. When sending the automated new-order alert to the owner, if the owner hasn't messaged the bot in 24 hours, the server uses a pre-approved **Utility Message Template** (e.g. `order_notification_v1` with dynamic variables and invoice/image header). Once the owner replies or asks a query, free-form text and media flow seamlessly.
2. **Dedicated Phone Number Requirement:**
   - Meta Cloud API requires a phone number dedicated to the API (it cannot be simultaneously logged into the standard WhatsApp phone app).
   - *Solution:* The Bot operates on a dedicated SIM / business number. The Owner uses their existing personal WhatsApp to interact with the bot.

### B. Business & Operational Edge Cases
1. **Ambiguous Customer Searches ("details about ali"):**
   - In any local market, multiple customers share names like Ali, Ahmed, Usman.
   - *Solution:* The AI must not hallucinate or pick one arbitrarily. If multiple records match, the AI returns a summarized list (Name, Phone, City, Order Date, Shoe Item) and asks: *"Which Ali do you want? Reply with 1 or 2"*.
2. **Flexible Search Modalities:**
   - The owner might not remember the customer's name when a courier calls. They might have a phone number, city, or shoe type:
     - Search by Phone: `"03001234567"`
     - Search by Shoe: `"who bought the air force 1 white?"`
     - Search by City: `"orders in Peshawar pending delivery"`
     - Search by Date: `"show orders from yesterday"`
3. **Thrift Shoe Inventory Clashes (1-of-1 Item Race Condition):**
   - Thrift shoes are unique single pairs. If two customers are sent the link at the same time, both might fill the form for the same shoe.
   - *Solution:* Introduce a simple `Shoe Code / Tag ID` (e.g., `#NK-42`) or quick link generator (`/order?item=NK-42`) that can mark items as reserved upon order generation.
4. **Data Security & Privacy:**
   - Only authorized phone numbers (Owner / Store Manager) must be allowed to query customer personal data and phone numbers from the WhatsApp bot. Any random user texting the bot will receive a polite greeting or order link, never customer PII.

---

## 5. Voice Notes & Multilingual AI Engine
The assistant handles natural communication in:
- **English** ("Give me details of Ali's order")
- **Roman Urdu / Hindi** ("Ali k joote ki picture aur address do", "Ali ka phone number kya hai?")
- **Urdu Script** ("علی کے جوتے کی تفصیل اور تصویر بھیجو")
- **Voice Notes (Audio .ogg)**:
  1. Meta Webhook triggers with `type == "audio"`.
  2. Bot downloads the raw audio file via `whatsapp_client.download_media()`.
  3. Sent to OpenAI Whisper API for real-time transcription.
  4. Transcribed text is passed directly into the AI Query Engine, matching queries exactly as if typed.


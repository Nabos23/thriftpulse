# Edge Cases, Process Flaws & Engineering Solutions

## 1. Customer Order Intake & Form Handling

| Problem / Flaw | Risk / Impact | Engineering Solution |
| :--- | :--- | :--- |
| **Heavy Image Uploads from Mobile Phones** | Customers upload 8MB - 15MB 4K photos taken from modern phones. This wastes bandwidth, fails on slow 3G/4G, and bloats server storage. | **Client-side compression:** Canvas-based image resizing and compression in Javascript before upload (reducing 10MB to ~300KB without visible quality loss for shoe identification). |
| **Duplicate / Ambiguous Thrift Items** | Thrift shoes are 1-of-1 pieces. If two customers upload a screenshot of the same shoe, you could accidentally sell it twice. | 1. Encourage a short **Shoe Tag / SKU** (e.g., `#NK-01`) marked on the shoe or in the listing post.<br>2. Add an optional pre-filled link: `order.yoursite.com/?code=NK-01`.<br>3. Once an order is confirmed, the item code is flagged as `Reserved`. |
| **Incomplete or Inaccurate Addresses** | Courier riders frequently fail deliveries because the customer wrote "Near Jamia Masjid" without house/street number. | Form field validation:<br>- Separate fields: `House/Street/Flat No`, `Area/Sector/Colony`, `City`, `Nearest Landmark`.<br>- Two phone numbers: Primary Phone + Alternate Phone (crucial for couriers when one is off). |
| **Customer Drop-off (Form Friction)** | A customer chatting on WhatsApp may abandon an external link if it asks for too much or loads slowly. | Clean, zero-bloat, 1-page mobile-optimized form with minimal inputs, auto-city selection, and one-tap camera/gallery upload. |

---

## 2. WhatsApp Cloud API Constraints & Server-Side Initiation

| Problem / Flaw | Risk / Impact | Engineering Solution |
| :--- | :--- | :--- |
| **Server Initiating WhatsApp Messages (24h Window)** | Meta Cloud API blocks free-form outbound messages if the recipient hasn't messaged the bot within 24 hours. If an order comes in 2 days after the owner last texted the bot, a normal text message will fail with HTTP 400. | **Approved Utility Message Template:**<br>Register a pre-approved Meta Template (e.g. `new_order_alert`) with header parameters (Invoice PDF link or Shoe image) and dynamic body variables (`Customer: {{1}}`, `City: {{2}}`, `Amount: {{3}}`).<br>Utility templates bypass the 24-hour window restriction! |
| **WhatsApp Media URL Expiration** | Media download URLs returned by Meta Graph API expire after 5 minutes. | When media is received via WhatsApp, the backend downloads the raw bytes **immediately** and saves them locally (`/uploads/shoes/...`) or to cloud storage with persistent URLs. |
| **Phone Number Collision** | The business owner's personal number cannot run on the standard WhatsApp mobile app and simultaneously be connected to the Meta Cloud API. | The bot runs on a **dedicated SIM / WhatsApp Business number**. The owner interacts with the bot from their personal WhatsApp number just like any other user. |

---

## 3. Owner AI Querying ("details about ali")

| Problem / Flaw | Risk / Impact | Engineering Solution |
| :--- | :--- | :--- |
| **Ambiguous Customer Name ("Ali")** | If 4 different customers named "Ali" bought shoes in the last month, a naive query might return the wrong customer or hallucinate. | **Disambiguation State Machine:**<br>The AI checks the DB. If count > 1, it lists summaries:<br>1. *Ali Khan - Lahore - Nike Jordan 1 (Oct 10)*<br>2. *Ali Raza - Karachi - New Balance 550 (Oct 12)*<br>Owner simply replies `1` or `2` to get the full card + shoe picture. |
| **Returning Media (Image of Shoes)** | An LLM generates text, but cannot directly "render" an image inside WhatsApp text. | **Function Calling / Multi-message dispatch:**<br>The AI invokes a tool `get_order_details(query="Ali")`. The tool returns JSON with the image path. The pipeline first sends the formatted text details, followed immediately by `whatsapp_client.send_image(to=owner, image_url=...)`. |
| **Varied Search Queries on the Go** | The owner might not know the name; the courier might only give the phone number or city. | The query engine supports multiple search filters:<br>- By Phone Number (`0300...`)<br>- By Order ID (`#ORD-104`)<br>- By Item / Brand / Size (`"Nike Air size 42"`)<br>- By Date (`"yesterday's orders"`)<br>- By Delivery Status (`"pending dispatch"`) |
| **Multilingual & Voice Note Queries** | The owner is often driving or on the move and sends quick Roman Urdu voice notes (e.g. *"Ali k joote ki tasveer bhejna"*). | The system automatically transcribes inbound voice notes (`.ogg`) using **OpenAI Whisper** and feeds the transcript to the GPT query pipeline, which natively understands English, Urdu, and Roman Urdu. |
| **Data Privacy & Unauthorized Access** | Anyone who finds the bot's WhatsApp number could query customer phone numbers and addresses. | **Strict Owner Whitelisting:**<br>The webhook inspects `sender_phone`. Only predefined owner/admin phone numbers in `.env` are permitted to execute query commands. Any other sender receives a polite generic customer greeting. |

---

## 4. Invoicing, Printing & Ledger Sync

| Problem / Flaw | Risk / Impact | Engineering Solution |
| :--- | :--- | :--- |
| **Invoice / Printing Needs for Couriers** | Courier riders need a compact waybill / thermal shipping slip (with customer address, COD price, shoe size, barcode/order number). | We generate both:<br>1. **80mm Thermal Slip (PDF / Image):** Perfect for mini portable Bluetooth thermal printers.<br>2. **WhatsApp Order Card:** Formatted WhatsApp text with clickable view/print link. |
| **Google Sheets Sync Failures** | If Google API is throttled, offline, or OAuth token expires, order creation could fail or hang. | **Database as Source of Truth:**<br>1. SQLite saves the order immediately with status `sheets_synced = False`.<br>2. Background task pushes to Google Sheets asynchronously.<br>3. Automatic retry queue if Google API errors occur. |

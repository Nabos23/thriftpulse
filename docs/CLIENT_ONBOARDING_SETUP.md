# Complete Client Onboarding & API Credentials Setup Guide

This guide walks you step-by-step through setting up all necessary accounts and generating the required `.env` credentials for a new client starting from zero (a normal Google account and a normal Facebook personal account).

---

## Quick Summary of Required Credentials

| Variable Name | Service | Purpose | Cost |
|---|---|---|---|
| `WHATSAPP_ACCESS_TOKEN` | Meta Developers | Sends order cards, photos & customer replies | Free tier (1,000 chats/mo) |
| `WHATSAPP_PHONE_NUMBER_ID` | Meta Developers | Identifies WhatsApp sender phone | Free |
| `WHATSAPP_WABA_ID` | Meta Developers | WhatsApp Business Account ID | Free |
| `WHATSAPP_VERIFY_TOKEN` | Any string | Secures webhook handshake | Free (custom secret) |
| `OWNER_PHONE_NUMBER` | WhatsApp | Phone number receiving owner alerts (e.g. `923XXXXXXXXX`) | Free |
| `GOOGLE_SERVICE_ACCOUNT_JSON`| Google Cloud | Appends orders & syncs to Google Sheets | 100% Free |
| `SPREADSHEET_ID` | Google Sheets | Destination spreadsheet | 100% Free |
| `TURSO_DATABASE_URL` | Turso | Cloud SQLite database | 100% Free (9GB, 500 DBs) |
| `TURSO_AUTH_TOKEN` | Turso | Database access token | Free |
| `CLOUDINARY_URL` | Cloudinary | Permanent image CDN hosting | 100% Free (25GB/mo) |
| `GROQ_API_KEY` | Groq Console | Free AI LLM + Voice STT (Whisper) | 100% Free |
| `BASE_URL` | Vercel | Your live production URL | Free |

---

## Phase 1: Meta WhatsApp Business API (From Personal Facebook)

### Step 1.1: Register as a Meta Developer
1. Log into your regular Facebook account.
2. Go to [developers.facebook.com](https://developers.facebook.com).
3. Click **Get Started** (top right) and accept the Developer terms.
4. Verify your phone number via SMS if prompted.

### Step 1.2: Create a Meta App
1. In the Meta Developer Dashboard, click **Create App**.
2. Select **Other** as the use case -> click **Next**.
3. Select **Business** as the app type -> click **Next**.
4. Enter an App Name (e.g., `ThriftPulse Client Store`) and your contact email.
5. Click **Create App** (enter Facebook password if asked).

### Step 1.3: Add WhatsApp to the App
1. In the App Dashboard sidebar, scroll to find **WhatsApp** and click **Set up**.
2. Under WhatsApp in the left menu, click **API Setup** (or **Quickstart**).
3. On this screen, you will immediately see:
   - **Temporary access token**
   - **Phone number ID** -> Copy this into `WHATSAPP_PHONE_NUMBER_ID`
   - **WhatsApp Business Account ID** -> Copy this into `WHATSAPP_WABA_ID`
   - A free Meta test phone number provided to start testing immediately.
   *(Note: To add the client's actual real SIM number, scroll down to "Step 5: Add a phone number" and follow SMS verification).*

### Step 1.4: Generate a Permanent System User Access Token
*(Temporary tokens expire in 24 hours. A System User token lasts permanently).*
1. Go to [business.facebook.com/settings](https://business.facebook.com/settings).
2. Select the client's Business Account.
3. In the left menu, click **Users** > **System Users**.
4. Click **Add** -> Name it `bot_admin` -> Set role to **Admin** -> Click **Create System User**.
5. Click **Assign Assets**:
   - Select **Apps** -> Select your created app -> Turn on **Full Control (Manage App)** -> Save.
6. Click **Generate New Token**:
   - Select your App from the dropdown.
   - Set Token Expiration to **Never** (or 60 days if required by policy).
   - Check the following two essential permissions:
     - `whatsapp_business_messaging`
     - `whatsapp_business_management`
   - Click **Generate Token**.
7. Copy the generated string -> This is your `WHATSAPP_ACCESS_TOKEN`.

### Step 1.5: Configure the Webhook
1. Go back to [developers.facebook.com](https://developers.facebook.com) > Your App > **WhatsApp** > **Configuration**.
2. Click **Edit** next to Callback URL:
   - **Callback URL**: `https://<your-vercel-domain>/webhook`
   - **Verify Token**: Any custom password string you choose, e.g. `thrift_bot_verify_2026` -> Put this in `WHATSAPP_VERIFY_TOKEN`.
3. Click **Verify and Save**.
4. Under **Webhook fields**, click **Manage** and subscribe to `messages`.

---

## Phase 2: Google Cloud & Google Sheets (From Standard Gmail)

### Step 2.1: Create a Google Cloud Project
1. Log into your standard Google/Gmail account.
2. Go to [console.cloud.google.com](https://console.cloud.google.com).
3. Click the Project dropdown at the top -> Click **New Project**.
4. Project Name: `Thrift Orders Sync` -> Click **Create**.
5. Ensure the new project is selected in the top bar.

### Step 2.2: Enable Google Sheets API
1. In the search bar at the top, type `Google Sheets API`.
2. Click on **Google Sheets API** from the results.
3. Click the blue **Enable** button.

### Step 2.3: Create a Service Account & Download Credentials
1. In the left navigation menu, go to **IAM & Admin** > **Service Accounts**.
2. Click **+ Create Service Account** (at the top).
3. Service account name: `sheets-bot` -> Click **Create and Continue**.
4. Role: Select **Basic** > **Editor** (or leave empty) -> Click **Done**.
5. You will see your new service account in the table (it looks like an email: `sheets-bot@project-id.iam.gserviceaccount.com`). Copy this email address!
6. Click the three dots (⋮) on the right side of the row -> Click **Manage keys**.
7. Click **Add Key** > **Create new key**.
8. Choose **JSON** -> Click **Create**.
9. A `.json` file will automatically download to your computer.

### Step 2.4: Prepare the Spreadsheet & Share
1. Go to [sheets.google.com](https://sheets.google.com) and create a **Blank spreadsheet**.
2. Name the spreadsheet (e.g. `Thrifted Shoes Orders`).
3. Name the first tab/sheet at the bottom `Orders`.
4. Copy the **Spreadsheet ID** from your browser's address bar:
   `https://docs.google.com/spreadsheets/d/`**`1vwfqpurRYzFZoI6eGugrzWi2W_AzsCLFMWSTDY3CxqE`**`/edit`
   -> Put this in `SPREADSHEET_ID`.
5. Click the green **Share** button (top right).
6. Paste the Service Account email (`sheets-bot@...iam.gserviceaccount.com`) from Step 2.3.
7. Set permission to **Editor**, uncheck "Notify people", and click **Share**.

### Step 2.5: Formatting the Credential for Vercel
- For local `.env`: Place the downloaded `.json` file in your project root as `service_account.json`.
- For Vercel production: Open the `.json` file in Notepad, copy the entire JSON text as a single string, and paste it into the `GOOGLE_SERVICE_ACCOUNT_JSON` environment variable in Vercel.

---

## Phase 3: Turso Cloud Database (Permanent SQLite)

1. Go to [turso.tech](https://turso.tech) and sign up with GitHub or email (100% Free).
2. Install the Turso CLI or create a database directly on the Turso Web Console:
   - Click **Create Database**.
   - Database name: `thrift-orders`
   - Region: Pick the region closest to your users (e.g., `aws-ap-south-1` for South Asia/Pakistan or `aws-us-east-1`).
3. Once created, click on your database:
   - Under **Database URL**, copy the `libsql://...` link -> Put this in `TURSO_DATABASE_URL`.
   - Click **Generate Token** -> Copy the long JWT token string -> Put this in `TURSO_AUTH_TOKEN`.

---

## Phase 4: Cloudinary Image CDN (Permanent Photo Hosting)

1. Go to [cloudinary.com](https://cloudinary.com) and sign up for a free account (No credit card required).
2. On the main **Dashboard** / **Console Home**, look at the top section labeled **Product Environment Credentials**:
3. You will see:
   - **Cloud name**
   - **API Key**
   - **API Secret**
   - **API environment variable**: Click the copy icon next to:
     `CLOUDINARY_URL=cloudinary://<api_key>:<api_secret>@<cloud_name>`
4. Copy the entire `CLOUDINARY_URL=...` string -> Put this in `CLOUDINARY_URL`.

---

## Phase 5: Groq Cloud API (Free AI LLM + Voice Notes Whisper)

1. Go to [console.groq.com](https://console.groq.com) and sign up with Google or GitHub (100% Free tier).
2. In the left menu, click **API Keys**.
3. Click **Create API Key**.
4. Name it `ThriftPulse Bot` and click **Submit**.
5. Copy the generated key (starts with `gsk_...`) -> Put this in `GROQ_API_KEY`.

---

## Phase 6: Final Deployment in Vercel

In your **Vercel Dashboard** > Your Project > **Settings** > **Environment Variables**, paste the following keys:

```env
# Meta WhatsApp API
WHATSAPP_ACCESS_TOKEN=<Permanent System User Token from Phase 1>
WHATSAPP_PHONE_NUMBER_ID=<Phone Number ID from Phase 1>
WHATSAPP_WABA_ID=<WABA ID from Phase 1>
WHATSAPP_VERIFY_TOKEN=thrift_bot_verify_2026
OWNER_PHONE_NUMBER=923XXXXXXXXX

# Google Sheets
SPREADSHEET_ID=<Spreadsheet ID from Phase 2>
ORDERS_SHEET_NAME=Orders
GOOGLE_SERVICE_ACCOUNT_JSON=<Paste the full contents of downloaded service account .json>

# Turso Cloud SQLite
TURSO_DATABASE_URL=<libsql://... from Phase 3>
TURSO_AUTH_TOKEN=<JWT token from Phase 3>

# Cloudinary
CLOUDINARY_URL=<cloudinary://... from Phase 4>

# Groq Free AI
GROQ_API_KEY=<gsk_... from Phase 5>
GROQ_MODEL=openai/gpt-oss-120b
GROQ_WHISPER_MODEL=whisper-large-v3-turbo

# App Configuration
ENVIRONMENT=production
BASE_URL=https://<your-project>.vercel.app
STORE_NAME=Thrifted Shoes PK
STORE_TAGLINE=Premium Pre-Loved Sneakers & Footwear
STORE_CONTACT=+92 312 9214688
```

After pasting these variables, click **Redeploy** on your latest deployment. Your client's store will be fully operational, permanent, and automated!

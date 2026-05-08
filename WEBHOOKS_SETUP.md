# Stripe webhooks + local run

This project reads Stripe settings from a **`.env`** file in the project root (that file is listed in `.gitignore` and must not be committed).

## Security note

Your **test** secret key (`sk_test_...`) has appeared in chat or screenshots before. Anyone with it can use your **sandbox** account in Stripe.

**Recommended:** In Stripe Dashboard go to **Developers → API keys**, open the menu next your **Secret key**, choose **Roll key**, copy the new secret, and replace `STRIPE_SECRET_KEY` in `.env`. You do not need to change any Python code.

---

## Easy way — one command: `python run.py`

A launcher script (`run.py`) is included in the project root. It does **everything** for you:

1. Creates / activates the project's `.venv` automatically.
2. Installs Python dependencies if they're missing.
3. Checks the Stripe CLI is installed and logged in.
4. Fetches the webhook signing secret from Stripe and writes it into `.env`.
5. Runs database migrations.
6. Starts the Stripe webhook forwarder **and** the Django dev server together, streaming both logs into the same terminal with `[stripe]` and `[django]` prefixes.
7. Stops both cleanly when you press **Ctrl+C**.

### One-time prerequisites (do these once per machine)

These two steps must be done by hand because `stripe login` requires you to approve in a browser. They are not something a script can do for you.

1. **Install the Stripe CLI**

   - macOS: `brew install stripe/stripe-cli/stripe`
   - Windows: `scoop install stripe` (or download from <https://github.com/stripe/stripe-cli/releases/latest>)

2. **Log the Stripe CLI into your Stripe sandbox**

   ```bash
   stripe login
   ```

   Approve in your browser. This is remembered for future runs.

3. **Fill in your Stripe API keys in `.env`**

   Copy `.env.example` to `.env` (the launcher will do this automatically the first time it runs) and set:

   ```env
   STRIPE_PUBLISHABLE_KEY=pk_test_...
   STRIPE_SECRET_KEY=sk_test_...
   ```

   You do **not** need to set `STRIPE_WEBHOOK_SECRET` by hand any more — `run.py` writes it for you.

### Run the project

From the project root:

```bash
python run.py
```

Then open <http://127.0.0.1:8000> in your browser. Press **Ctrl+C** in the terminal to stop everything.

> If you see "Stripe CLI was not found" or "Stripe CLI is installed but not logged in", just complete the relevant one-time step above and re-run `python run.py`.

---

## Manual way (advanced)

If you prefer to run each piece in its own terminal — or you want to understand what `run.py` is doing under the hood — follow the original steps below. Both ways work; pick whichever you prefer.

## Step 1 — Install Stripe CLI (one time)

If you use Homebrew:

```bash
brew install stripe/stripe-cli/stripe
```

Check it works:

```bash
stripe --version
```

---

## Step 2 — Log the CLI into your Stripe sandbox

From any folder:

```bash
stripe login
```

Your browser opens; approve access. This links the CLI to the same Stripe account you use in the Dashboard (sandbox / test mode).

---

## Step 3 — Forward webhooks to your laptop

Leave this terminal **open** while you test payments.

From the project root (or any folder):

```bash
stripe listen --forward-to localhost:8000/stripe/webhook/
```

You should see a line like:

`Ready! Your webhook signing secret is whsec_xxxxxxxx (...)`  

Copy the **`whsec_...`** value.

Open **`.env`** in the project root and set:

```env
STRIPE_WEBHOOK_SECRET=whsec_paste_the_full_value_here
```

Save the file.

> **Why this exists:** Stripe signs each webhook so your app knows the request is really from Stripe. `STRIPE_WEBHOOK_SECRET` is that signing secret for your local tunnel.

---

## Step 4 — Run the Django app

Open a **second** terminal. From the project root:

```bash
cd "/path/to/EventEats-clean"
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

If you do not have `.venv` yet, create it once:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Visit **`http://127.0.0.1:8000`** (this matches `SITE_URL` in `.env`).

---

## Try a test payment

1. Register / log in as a **normal user** (customer role).
2. Open a **published** event that has food items.
3. Choose quantities and click **Proceed to payment (AUD)**.
4. On Stripe Checkout use test card **`4242 4242 4242 4242`**, any future expiry, any CVC, any postcode.

What should happen:

- You return to the success page after paying.
- With **`stripe listen`** running** and **`STRIPE_WEBHOOK_SECRET`** set, your app receives `checkout.session.completed` and **My Bookings** should show **Paid**.

If webhooks are not configured (`STRIPE_WEBHOOK_SECRET` empty or `stripe listen` not running), checkout can still succeed on Stripe’s side, but the app may keep the booking as **Payment pending** until the webhook works.

---

## What `SITE_URL` is

`SITE_URL` is the **base URL of your running site**. For local development it should match how you open the browser, for example:

```env
SITE_URL=http://127.0.0.1:8000
```

Stripe uses it (with your success/cancel paths) to send the customer back after Checkout. If you use `http://localhost:8000` instead, update `SITE_URL` to match.

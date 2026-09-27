# Pharmacole — Multi-Tenant Pharmacy SaaS

Pharmacole is a SaaS platform for pharmacies in Ghana. Owners sign up, pay
**GH₵ 500/month** via Paystack, and get instant access to a full management
dashboard: POS, inventory, expiry tracking, employee management, and analytics.

> **No free trial. No grace period.** After one month the system automatically
> locks the tenant out until they renew.

---

## Tech Stack

| Layer       | Technology                              |
|-------------|-----------------------------------------|
| Backend     | Python 3.11+ · Flask 3                  |
| Database    | MongoDB (Atlas or local)                |
| Templates   | Jinja2 + Tailwind CSS (CDN)             |
| Payments    | Paystack (GHS, monthly)                 |
| Deployment  | Linux VPS · Gunicorn · Nginx · systemd  |

---

## Project Structure
pharmacole/
├── app/
│ ├── init.py # create_app factory
│ ├── errors.py # error handlers
│ ├── blueprints/ # auth, main, payments, webhooks, owner, pharmacist, cashier, super_admin
│ └── services/ # business logic per collection
├── templates/
│ ├── base.html # public base
│ ├── auth/, errors/, owner/, pharmacist/, cashier/, super-admin/
│ └── _flashes.html
├── static/ # css, js, manifest, robots, sitemap
├── scripts/ # seed_super_admin.py, ensure_indexes.py, reset_db.py
├── tests/ # pytest
├── config.py
├── extensions.py
├── models.py
├── utils.py
├── decorators.py
├── run.py
├── wsgi.py
└── requirements.txt



---

## Local Setup

```bash
git clone <repo> pharmacole
cd pharmacole
python -m venv venv
source venv/bin/activate          # or venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env              # fill in real values
python -m scripts.ensure_indexes
python -m scripts.seed_super_admin
python run.py
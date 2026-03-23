# 💰 Leozera – AI-Powered Financial Assistant (SaaS)

> A smart financial management platform with an AI assistant integrated into WhatsApp.  
> Track expenses, receive insights, and manage your finances effortlessly through natural language.

---

## ✨ Overview

**Leozera** is a SaaS platform designed to simplify personal finance management using AI.

Users can:

- Register expenses via WhatsApp using natural language
- Monitor financial health through a smart dashboard
- Receive automated insights and recommendations
- Manage subscriptions and financial routines

The system combines **AI + messaging + analytics** to create a frictionless financial experience.

---

## 🚀 Core Features

### 💬 AI Financial Assistant (WhatsApp)

- Natural language expense tracking  
  _"I spent 45 reais at the supermarket"_
- Automatic categorization of transactions
- Account recognition (which account was used)
- Transaction correction via chat
- Financial report generation on demand
- Intelligent intent classification (transaction, correction, report, agenda, etc.)

---

### 📊 Smart Financial Dashboard

- Balance evolution over time
- Expenses by category
- Expenses by weekday
- Expenses by time of day
- Expense distribution
- Expenses by account

---

### 🧠 Intelligent Insights

- Savings rate calculation
- Financial health score (visual indicator)
- Highest spending category detection
- Alerts when a category exceeds 30% of expenses
- Account with highest spending
- Month-over-month trend analysis
- "Money velocity" (how long income sustains expenses)

---

### 📈 AI Financial Analysis

Each report includes:

- Diagnosis  
- Impact  
- Projection  
- Recommendation  

---

### 📅 Smart Agenda

- Create appointments via chat
- Automatic confirmation
- Reminder notifications (12h and 1h before) via WhatsApp

---

### 💳 Subscription System

- Free trial (7 days)
- Monthly and yearly plans via Mercado Pago
- Subscription management dashboard
- Cancellation flow
- Automatic downgrade (Celery workers)
- Feature access control based on subscription

---

### 🧾 Transaction System

- Manual dashboard entries
- AI-powered categorization (future enhancement)
- Multi-account support
- Custom categories per user

---

### 📢 Community & Updates

- Internal updates page (features, improvements, fixes)
- User feedback system:
  - Suggestions
  - Bug reports (sent via email)

---

## 🏗️ Architecture

- Django-based web application
- MongoDB for data storage
- WhatsApp integration (WAHA API)
- AI processing via OpenAI
- Background workers (Celery + Redis)
- Financial dashboard with analytics layer

---

## 🛠️ Tech Stack

### Backend
- Python
- Django
- MongoDB

### Frontend
- HTML
- TailwindCSS
- JavaScript

### Infrastructure
- PythonAnywhere (deployment)
- Redis (task queue)
- Docker (optional services)

### AI
- OpenAI API
- LangChain (agent orchestration)

---

## ⚙️ Installation

### Requirements

- Python 3.11+
- MongoDB
- Redis
- API keys:
  - OpenAI
  - Mercado Pago
  - WhatsApp (WAHA)
  - Email service (Resend or similar)

---

### Setup

```bash
git clone https://github.com/your-username/leozera.git
cd leozera
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate
```
pip install -r requirements.txt
Environment Variables

Create a .env file:

SECRET_KEY=your_secret_key
DEBUG=True

MONGO_USER=your_user
MONGO_PASS=your_password
MONGO_HOST=your_host
MONGO_DB_NAME=your_db

REDIS_URL=redis://localhost:6379/0

OPENAI_API_KEY=your_key

MP_ACCESS_TOKEN=your_token
MP_WEBHOOK_SECRET=your_secret

RESEND_API_KEY=your_email_key
EMAIL_FROM=your_email

WAHA_API_URL=your_url
WAHA_API_KEY=your_key
WAHA_SESSION=default
Run the Application
python manage.py migrate
python manage.py runserver
Run Workers (Celery)
cd agent_ia

celery -A celery_app.celery worker --loglevel=info
celery -A celery_app.celery beat --loglevel=info

---

###🔄 Versioning

###Current version: v0.4.1

Highlights
Full onboarding system with guided tour
First-time user checklist
Financial account system
Improved UX and dashboard insights
Subscription and billing system
AI-powered transaction interpretation

---

##🔐 Security
Authentication via Django sessions
Email verification with token
Password reset flow
Secure API endpoints (no client-side user injection)
Mercado Pago webhook validation
Controlled access based on subscription status

--- 

##🌎 Deployment

Example: PythonAnywhere

git pull origin main
pip install -r requirements.txt

Then reload the application via the dashboard.

---

##⚠️ Notes
Designed to augment financial awareness, not replace financial advisors
No direct bank integration (manual account tracking)
AI decisions are assistive, not authoritative

---

##📈 Business Vision

Leozera aims to:

Reduce friction in financial tracking
Increase financial awareness
Automate repetitive financial tasks
Deliver actionable insights through AI

---

##👨‍💻 Author

Developed by Vinícius de Pires

---

##📄 License

Proprietary software. Usage and distribution are restricted.

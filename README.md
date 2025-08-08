# Wells Fargo Application Automation

This script uses Playwright to:

- Navigate to a provided Wells Fargo application link
- Click "Yes" for "Are you a Wells Fargo customer?"
- Click "Continue without signing on"
- Take screenshots along the way
- Scroll to Important Disclosures / Terms and Conditions
- Click the Print button and save the resulting document as PDF
- Capture any downloaded PDFs

## Setup

1. Create and activate a virtual environment (optional):

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
python -m playwright install --with-deps
```

## Run

```bash
python app/main.py
```

Outputs will be saved under `outputs/` with timestamped folders containing screenshots and PDFs.

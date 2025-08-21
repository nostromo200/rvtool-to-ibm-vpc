# RVTools → IBM Cloud VPC Matcher

Flask app that reads an RVTools Excel export and matches VMs to IBM Cloud VPC instance profiles (excluding **bz2** family).

## Deploy to IBM Cloud Code Engine

- Push this repo to GitHub/GitLab/etc.
- In Code Engine, create an **application** and point it at your repo.
- Add an environment variable or secret `IBM_CLOUD_API_KEY`.
- Optional: set `IBM_VPC_SERVICE_URL` (defaults to `https://us-south.iaas.cloud.ibm.com/v1`).
- Port: `8080`.

The start command is provided via `Procfile`.

### Local run
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export IBM_CLOUD_API_KEY=your-key
python app.py
# open http://localhost:8080
```

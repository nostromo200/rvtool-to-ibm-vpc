from flask import Flask, request, render_template
import pandas as pd
import os
import logging
import re
from werkzeug.utils import secure_filename

from ibm_vpc import VpcV1
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

logging.basicConfig(level=logging.INFO)

SERVICE_URL = os.environ.get('IBM_VPC_SERVICE_URL', 'https://us-south.iaas.cloud.ibm.com/v1')
API_KEY = os.environ.get('IBM_CLOUD_API_KEY')

def _ensure_api_key():
    global API_KEY
    if API_KEY:
        return API_KEY
    try:
        import getpass
        API_KEY = getpass.getpass('Enter IBM Cloud API key: ')
    except Exception:
        API_KEY = input('Enter IBM Cloud API key: ')
    return API_KEY

def vpc_client():
    key = _ensure_api_key()
    authenticator = IAMAuthenticator(key)
    svc = VpcV1(version='2025-04-29', authenticator=authenticator)
    svc.set_service_url(SERVICE_URL)
    return svc

def get_vpc_profiles():
    svc = vpc_client()
    profiles_list = []
    resp = svc.list_instance_profiles()
    result = resp.get_result() or {}
    for p in result.get('profiles', []):
        name = p.get('name', '')
        if 'bz2' in name.lower():
            continue
        m = re.search(r'-(\d+)[xX](\d+)', name)
        if not m:
            continue
        cpus = int(m.group(1))
        mem = int(m.group(2))
        profiles_list.append((cpus, mem, name))
    profiles_list.sort(key=lambda t: (t[0], t[1], t[2]))
    return profiles_list

def get_vpc_prices():
    svc = vpc_client()
    price_dict = {}
    try:
        resp = svc.list_instance_profiles()
        result = resp.get_result() or {}
        for p in result.get('profiles', []):
            name = p.get('name', '')
            if 'bz2' in name.lower():
                continue
            price = (p.get('price') or {}).get('value')
            if price is not None:
                try:
                    price_dict[name] = float(price)
                except Exception:
                    pass
    except Exception as e:
        logging.warning("Pricing retrieval failed: %s", e)
    return price_dict

def round_memory_mb_to_gb(mem_mb):
    if pd.isna(mem_mb):
        return 0
    try:
        mem_mb = float(mem_mb)
    except Exception:
        return 0
    return int((mem_mb + 1023) // 1024)

def best_match(cpus, mem_gb, profiles):
    if pd.isna(cpus) or pd.isna(mem_gb):
        return "Unknown"
    try:
        need_cpu = int(cpus)
        need_mem = int(mem_gb)
    except Exception:
        return "Unknown"
    for c, m, name in profiles:
        if c >= need_cpu and m >= need_mem:
            return name
    return "Unknown"

@app.route('/', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        file = request.files.get('file')
        if not file:
            return render_template('upload.html', error="Please select a file")
        filename = secure_filename(file.filename)
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)

        df = pd.read_excel(filepath, sheet_name='vInfo', engine='openpyxl')
        df['CPUs'] = pd.to_numeric(df.iloc[:, 14], errors='coerce')
        df['MemoryMB'] = pd.to_numeric(df.iloc[:, 15], errors='coerce')
        df['Mem Rounded'] = df['MemoryMB'].apply(round_memory_mb_to_gb)

        vpc_profiles = get_vpc_profiles()
        vpc_prices = get_vpc_prices()

        df['Instance Profile'] = df.apply(lambda r: best_match(r['CPUs'], r['Mem Rounded'], vpc_profiles), axis=1)
        df['VPC Price ($)'] = df['Instance Profile'].map(vpc_prices)

        summary = (df.groupby('Instance Profile', dropna=False)
                     .agg(Count=('Instance Profile', 'size'),
                          Total_Price=('VPC Price ($)', 'sum'))
                     .reset_index())

        df_display = df.copy()
        df_display['VPC Price ($)'] = df_display['VPC Price ($)'].apply(lambda x: f"${x:.2f}" if pd.notna(x) else "")

        summary_display = summary.copy()
        summary_display['Total_Price'] = summary_display['Total_Price'].apply(lambda x: f"${x:.2f}" if pd.notna(x) else "$0.00")

        return render_template('table.html',
            summary_table=summary_display.to_html(classes='summary', index=False, escape=False),
            data_table=df_display.to_html(classes='data', index=False, escape=False))

    return render_template('upload.html')

if __name__ == '__main__':
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

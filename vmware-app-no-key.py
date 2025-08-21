from flask import Flask, request, render_template, send_file
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

# Configure logging
logging.basicConfig(level=logging.DEBUG)

# IBM Cloud VPC Setup (runtime key: env var or console input)
SERVICE_URL = 'https://us-south.iaas.cloud.ibm.com/v1'
API_KEY = os.environ.get('IBM_CLOUD_API_KEY')
if not API_KEY:
    try:
        import getpass
        API_KEY = getpass.getpass('Enter IBM Cloud API key: ')
    except Exception:
        API_KEY = input('Enter IBM Cloud API key: ')
authenticator = IAMAuthenticator(API_KEY)
vpc_service = VpcV1(version='2025-04-29', authenticator=authenticator)
vpc_service.set_service_url(SERVICE_URL)

def get_vpc_profiles():
    response = vpc_service.list_instance_profiles()
    profiles_list = []
    if response.get_result():
        for profile in response.get_result()['profiles']:
            name = profile['name']
            match = re.search(r'-(\d+)x(\d+)', name)
            if match:
                cpus = int(match.group(1))
                memory = int(match.group(2))
                profiles_list.append((cpus, memory, name))
                logging.debug(f"Profile extracted: {name} -> CPUs: {cpus}, Memory: {memory}GB")
    
    # Sort profiles by CPU then Memory for optimized selection
    profiles_list.sort()
    # Exclude bz2 family from consideration
    profiles_list = [t for t in profiles_list if 'bz2' not in t[2].lower()]
    logging.debug(f"Total profiles retrieved: {len(profiles_list)}")
    return profiles_list

def get_vpc_prices():
    response = vpc_service.list_instance_profiles()
    price_dict = {}
    if response.get_result():
        for profile in response.get_result()['profiles']:
            name = profile['name']
            price = profile.get('price', {}).get('value', None)
            if price:
                price_dict[name] = float(price)
                logging.debug(f"Pricing found: {name} -> ${price}")
            else:
                logging.debug(f"No pricing found for: {name}")
    logging.debug(f"Total pricing entries retrieved: {len(price_dict)}")
    # Exclude bz2-priced profiles
    price_dict = {k:v for k,v in price_dict.items() if 'bz2' not in k.lower()}
    return price_dict  # kept for reference


# Memory rounding function
def round_memory(mem):
    thresholds = [128, 1024, 2048, 4096, 6136, 8192, 12288, 16384, 24576, 32768]
    rounded_values = [0, 1, 2, 4, 6, 8, 12, 16, 24, 32]
    for i, threshold in enumerate(thresholds):
        if mem <= threshold:
            return rounded_values[i]
    return 32  # Default for higher values

def find_best_match(cpus, mem_rounded, profiles_list):
    for profile_cpus, profile_memory, profile_name in profiles_list:
        if profile_cpus >= cpus and profile_memory >= mem_rounded:
            logging.debug(f"Matched profile: {profile_name} for CPUs: {cpus}, Mem: {mem_rounded}")
            return profile_name
    
    logging.debug(f"No match found for CPUs: {cpus}, Mem: {mem_rounded}")
    return "Unknown"

@app.route('/', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        file = request.files['file']
        if file:
            filename = secure_filename(file.filename)
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            file.save(filepath)
            
            # Load Excel
            df = pd.read_excel(filepath, sheet_name='vInfo')
            
            # Keep Excel headers as read; do NOT drop the first data row.
            
            # Extract CPU and Memory from specified columns (Column O and P)
            df.loc[:, 'CPUs'] = pd.to_numeric(df.iloc[:, 14], errors='coerce')  # Column O (index 14)
            df.loc[:, 'Memory'] = pd.to_numeric(df.iloc[:, 15], errors='coerce')  # Column P (index 15)
            
            df.loc[:, 'Mem Rounded'] = df['Memory'].apply(round_memory)
            
            # Fill NaN values with 0 for safe conversion
            df.loc[:, 'CPUs'] = df['CPUs'].fillna(0).astype(int)
            df.loc[:, 'Mem Rounded'] = df['Mem Rounded'].fillna(0).astype(int)
            
            # Get IBM Cloud VPC profiles and prices
            vpc_profiles = get_vpc_profiles()
            vpc_prices = get_vpc_prices()
            
            # Assign profiles with best match logic
            df.loc[:, 'Instance Profile'] = df.apply(lambda row: find_best_match(row['CPUs'], row['Mem Rounded'], vpc_profiles), axis=1)
            
            # Assign prices
            df.loc[:, 'VPC Price ($)'] = df['Instance Profile'].map(vpc_prices)
            
            # Generate summary table
            summary_df = df.groupby('Instance Profile').agg(
                Number_Listed=('Instance Profile', 'count'),
                Total_Price=('VPC Price ($)', 'sum')
            ).reset_index()
            summary_df['Total_Price'] = summary_df['Total_Price'].apply(lambda x: f"${x:.2f}" if pd.notna(x) else "$0.00")
            
            # Debugging output
            logging.debug(f"Processed Data:\n{df[['CPUs', 'Memory', 'Mem Rounded', 'Instance Profile', 'VPC Price ($)']].head()}")
            logging.debug(f"Summary Data:\n{summary_df}")
            
            # Display processed data with explicit column titles
            return render_template('table.html',
                                   summary_table=summary_df.to_html(classes='summary', index=False, escape=False),
                                   data_table=df.to_html(classes='data', index=False, escape=False))
    
    return render_template('upload.html')

if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)
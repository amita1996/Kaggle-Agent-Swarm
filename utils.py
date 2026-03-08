import os
import re
import zipfile
from kaggle.api.kaggle_api_extended import KaggleApi
from dotenv import load_dotenv

load_dotenv("keys.env")

def download_kaggle_data(competition_url, path='./data'):
    print(f'Competition URL = {competition_url}')
    # 1. Set Credentials
    os.environ['KAGGLE_USERNAME'] = os.getenv("KAGGLE_USERNAME")
    os.environ['KAGGLE_KEY'] = os.getenv("KAGGLE_KEY")

    # 2. Extract competition slug
    match = re.search(r"competitions/([^/]+)", competition_url)
    if not match:
        print("Error: Could not find a valid competition slug.")
        return

    competition_slug = match.group(1)

    # 3. Initialize and Authenticate
    api = KaggleApi()
    api.authenticate()

    # 4. Download the zip file
    if not os.path.exists(path):
        os.makedirs(path)

    print(f"Downloading data for: {competition_slug}...")
    # Removed the 'unzip' argument that caused the crash
    api.competition_download_files(competition_slug, path=path, quiet=False)

    # 5. Manually Unzip
    zip_path = os.path.join(path, f"{competition_slug}.zip")

    if os.path.exists(zip_path):
        print(f"Unzipping {zip_path}...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(path)

        # Optional: Remove the zip file after extracting to save space
        os.remove(zip_path)
        print(f"Success! Files extracted to: {os.path.abspath(path)}")
    else:
        print(f"Error: Downloaded file {zip_path} not found.")


if __name__ == "__main__":
    # Example Usage:
    url = "https://www.kaggle.com/competitions/linking-writing-processes-to-writing-quality/data"
    download_kaggle_data(url)
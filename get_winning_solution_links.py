import pandas as pd
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager


def extract_competition_data_as_string(competition_name, csv_path="kaggle_competitions_corrected.csv"):
    # 1. Read the CSV and locate the URL for the specified competition
    try:
        df = pd.read_csv(csv_path)
    except FileNotFoundError:
        return f"Error: Could not find the file {csv_path}"

    # Look up the competition using a partial match (case-insensitive)
    match = df[df['Competition'].str.contains(competition_name, case=False, na=False)]

    if match.empty:
        return f"Competition containing '{competition_name}' not found in the CSV."

    found_name = match.iloc[0]['Competition']
    url = match.iloc[0]['URL']
    print(f"Matched '{found_name}' -> URL: {url}")

    # 2. Set up the Selenium WebDriver in HEADLESS mode
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--window-size=1920,1080")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)

    try:
        # 3. Go to the URL
        driver.get(url)
        print("Page loading... waiting 3 seconds for initial render.")
        time.sleep(3)

        # 4. Inject and execute the async Javascript snippet
        js_code = """
        var callback = arguments[arguments.length - 1]; 

        (async () => {
          // 1. Find and click the 'EXPAND ALL' button
          const expandBtn = Array.from(document.querySelectorAll('button'))
            .find(b => b.innerText.includes('EXPAND ALL'));

          if (expandBtn) {
            expandBtn.click();
            await new Promise(r => setTimeout(r, 500));
          }

          // 2. Get ALL Kaggle competition links on the page
          const allKaggleLinks = Array.from(document.querySelectorAll('a[href*="kaggle.com/competitions/"]'))
            .map(a => a.href);

          // 3. Extract the Main Kaggle Link (the one without '/discussion/')
          const mainLink = allKaggleLinks.find(href => !href.includes('/discussion/')) || "Main link not found";

          // 4. Extract and deduplicate Discussion links
          const discussionLinks = allKaggleLinks.filter(href => href.includes('/discussion/'));
          const uniqueDiscussionLinks = [...new Set(discussionLinks)];

          // 5. Return an object back to Python
          callback({
              "main_link": mainLink,
              "discussion_links": uniqueDiscussionLinks
          }); 
        })();
        """

        print("Executing Javascript extraction...")
        driver.set_script_timeout(15)

        # Execute script. It now returns a Python dictionary!
        extracted_data = driver.execute_async_script(js_code)

        # 5. Format the dictionary into a nice string
        if extracted_data:
            main_link = extracted_data.get("main_link")
            discussion_links = extracted_data.get("discussion_links", [])

            # Build the output string
            output = []
            output.append(f"--- MAIN KAGGLE LINK ---")
            output.append(main_link)
            output.append(f"\n--- DISCUSSION LINKS ({len(discussion_links)} Found) ---")

            if discussion_links:
                output.append("\n".join(discussion_links))
            else:
                output.append("No discussion links were found on the page.")

            return "\n".join(output)
        else:
            return "Script executed but returned no data."

    except Exception as e:
        return f"An error occurred during extraction: {e}"

    finally:
        driver.quit()


import pandas as pd
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager


def get_kaggle_tuple(competition_name, csv_path="kaggle_competitions_corrected.csv"):
    """
    Returns: (str: main_kaggle_link, list: solution_links)
    """
    # 1. Read CSV and find the URL using partial match
    try:
        df = pd.read_csv(csv_path)
    except FileNotFoundError:
        return None, []

    match = df[df['Competition'].str.contains(competition_name, case=False, na=False)]

    if match.empty:
        return None, []

    url = match.iloc[0]['URL']

    # 2. Configure Headless Selenium
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--window-size=1920,1080")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)

    try:
        driver.get(url)
        time.sleep(10)  # Wait for initial render

        # 3. Async JavaScript to extract links
        js_code = """
        var callback = arguments[arguments.length - 1]; 

        (async () => {
          // Click 'EXPAND ALL' to reveal all links
          const expandBtn = Array.from(document.querySelectorAll('button'))
            .find(b => b.innerText.includes('EXPAND ALL'));

          if (expandBtn) {
            expandBtn.click();
            await new Promise(r => setTimeout(r, 600)); // Wait for expansion
          }

          const allLinks = Array.from(document.querySelectorAll('a[href*="kaggle.com/competitions/"]'))
            .map(a => a.href);

          // The main competition link doesn't have '/discussion/' in it
          const mainLink = allLinks.find(href => !href.includes('/discussion/')) || "";

          // The winning solution links are the discussion links
          const solutionLinks = [...new Set(allLinks.filter(href => href.includes('/discussion/')))];

          callback({
              "main": mainLink,
              "solutions": solutionLinks
          }); 
        })();
        """

        driver.set_script_timeout(15)
        data = driver.execute_async_script(js_code)

        # 4. Return as a Tuple
        return (data["main"], data["solutions"])

    except Exception as e:
        print(f"Error: {e}")
        return None, []

    finally:
        driver.quit()


# ==========================================
# Example usage
# ==========================================
if __name__ == "__main__":
    # Example: Searching for a partial match
    kaggle_url, solutions = get_kaggle_tuple("fast or slow")

    print(f"Kaggle Competition: {kaggle_url}")
    print(f"Found {len(solutions)} winning solutions.")
    print(solutions)

    # This is now a standard Python tuple
    my_data_tuple = (kaggle_url, solutions)
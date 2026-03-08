import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from get_winning_solution_links import get_kaggle_tuple

def scrape_kaggle_text(kaggle_url, solution_links):
    """
    Takes the main kaggle URL and a list of solution links.
    Returns:
        competition_text (str): Combined text from the main page and the /data page.
        solutions_texts (list of str): A list where each element is the text from a solution page.
    """
    # 1. Configure Headless Selenium
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--window-size=1920,1080")

    # Optional: block images/css to speed up scraping
    prefs = {"profile.managed_default_content_settings.images": 2,
             "profile.managed_default_content_settings.stylesheets": 2}
    chrome_options.add_experimental_option("prefs", prefs)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)

    competition_text = ""
    solutions_texts = []

    try:
        # ==========================================
        # 1. Scrape Main Competition Page & Data Page
        # ==========================================
        if kaggle_url:
            print(f"Scraping main page: {kaggle_url}")
            driver.get(kaggle_url)
            time.sleep(4)  # Wait for Kaggle's React frontend to render

            # Extract all visible text on the page
            main_text = driver.find_element(By.TAG_NAME, "body").text
            competition_text += f"--- MAIN PAGE ({kaggle_url}) ---\n{main_text}\n\n"

            # Navigate to the /data page
            # rstrip ensures we don't end up with an accidental double slash like //data
            data_url = kaggle_url.rstrip("/") + "/data"
            print(f"Scraping data page: {data_url}")
            driver.get(data_url)
            time.sleep(4)

            data_text = driver.find_element(By.TAG_NAME, "body").text
            competition_text += f"--- DATA PAGE ({data_url}) ---\n{data_text}\n\n"

        # ==========================================
        # 2. Scrape Each Solution Page
        # ==========================================
        for i, link in enumerate(solution_links):
            print(f"Scraping solution {i + 1}/{len(solution_links)}: {link}")
            driver.get(link)
            time.sleep(4)  # Wait for rendering

            sol_text = driver.find_element(By.TAG_NAME, "body").text
            solutions_texts.append(sol_text)

    except Exception as e:
        print(f"An error occurred during text scraping: {e}")

    finally:
        driver.quit()

    return competition_text, solutions_texts


def get_context_data(competition_input):
    # Check if the user provided a direct URL
    if competition_input.startswith("http"):
        kaggle_url = competition_input
        solutions = []
    else:
        kaggle_url, solutions = get_kaggle_tuple(competition_input)

    print(f"Kaggle URL: {kaggle_url}")
    print(f"Solution links len: {len(solutions)}")

    solutions = solutions[:3]

    print("Starting scraping process...")
    comp_text, sol_text_list = scrape_kaggle_text(kaggle_url, solutions)

    print("\n--- DONE ---")
    print(f"Competition text length: {len(comp_text)} characters.")
    print(f"Scraped {len(sol_text_list)} solution pages.")

    return comp_text, sol_text_list, kaggle_url


# ==========================================
# Example Integration
# ==========================================
if __name__ == "__main__":

    comp_text, sol_text_list, kaggle_url = get_context_data('fast or slow')

    print("\n--- DONE ---")
    print(f"Competition text length: {len(comp_text)} characters.")
    print(f"Scraped {len(sol_text_list)} solution pages.")

    print('comp text')
    print(comp_text)

    print('sol text')
    print(sol_text_list)
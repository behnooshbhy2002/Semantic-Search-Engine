# Specific libraries for web scraping
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys

# Library to delay when loading web page
import time
from datetime import datetime

# Library to work with CSV files
import csv


def scroll_to_bottom(driver):
    last_height = driver.execute_script("return document.body.scrollHeight")
    while True:
        # Scroll down to the bottom
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        # Wait for new content to load
        time.sleep(3)
        # Calculate new scroll height and compare with last scroll height
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height


def return_number_of_pages(driver):
    number_of_pages = 0
    try: 
        num_pages_list = driver.find_elements(
            By.CSS_SELECTOR,
            "div.pagination_container nav ul li"
        )
        number_of_pages = int(num_pages_list[-2].text)

    except Exception as e:
        print("An error occurred when extract pagation details: ", e)
    
    return number_of_pages


def extract_abs_text(article):
    abs_text = ''
    try:
        abs_button = article.find_element(By.CSS_SELECTOR, "div.tab-header.ng-scope")
        abs_button.click()

        time.sleep(4)

        abs_content = article.find_element(
            By.CSS_SELECTOR,
            ".abstract p span"
        )
        abs_text = abs_content.text
        print("Abstract got extracted.")

    except Exception as e:
        print(f"Abstract not found or an error occurred: {e}")

    return abs_text


def extract_keywords(article):
    keyword_text = ''
    try:
        keyword_button = article.find_element(By.CSS_SELECTOR, "#secondary_tabs > div:nth-child(2) > div")
        keyword_button.click()

        time.sleep(4)
        
        keyword_content = article.find_element(
            By.CSS_SELECTOR,
            ".keywords div"
        )
        keyword_text = keyword_content.text
        print("Keywords got extracted.")
        # print(keyword_text)

    except:
        print("Keywords not found")
    
    return keyword_text


def click_next_page(driver):
    try:
        next_button = driver.find_element(
            By.XPATH,
            "//ul[contains(@class,'pagination')]//a[.//span[contains(text(),'»')]]"
        )
        next_button.click()
    except Exception as e:
        print("An error occurred:", e)


def crawl_current_page(driver):
    wait = WebDriverWait(driver, 30)
    scroll_to_bottom(driver)

    csv_file = open("ganj_results.csv", "w", newline="", encoding="utf-8")
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow(["id", "meta_text", "abs_text", "keyword_text"])

    number_of_pages = return_number_of_pages(driver)

    if number_of_pages == 0:
        print("Your query doesn't have any search results!!!")
        return
    
    else:
        page_counter = 1
        article_counter = 0
        while page_counter <= number_of_pages:

            article_cards = driver.find_elements(
                By.CSS_SELECTOR,
                ".result-list-padding > div"
            )

            print(f"Number of article_cards on page {page_counter}: {len(article_cards) - 1}")   

            for index, article in enumerate(article_cards[:-1], start=1):
                meta_text = ''
                abs_text = ''
                keyword_text = ''
                article_counter += 1
                try:
                    print("\n" + "="*50)
                    print(f"Article #{article_counter}")

                    # Article Matadata
                    meta_text = article.text
                    print("Mata data got saved.")

                    # Abstract
                    abs_text = extract_abs_text(article)                   

                    # Keywords
                    keyword_text = extract_keywords(article)

                    # Save to CSV
                    csv_writer.writerow([article_counter, meta_text, abs_text, keyword_text])
                    print("Saved to CSV file")

                except Exception as e:
                    print("Error in this article:", e)
            
            click_next_page(driver)
            time.sleep(6)

            page_counter += 1
            number_of_pages = return_number_of_pages(driver)

    csv_file.close()
    print("CSV file closed")


def search(driver, prompt="هوش مصنوعی"):
    wait = WebDriverWait(driver, 20)
    try:
        # Wait until input appears
        search_box = wait.until(
            EC.presence_of_element_located((By.TAG_NAME, "input"))
        )

        search_box.clear()
        search_box.send_keys(prompt)
        search_box.send_keys(Keys.ENTER)

        # Wait for results to load
        time.sleep(5)
        driver.refresh()
        time.sleep(5)

    except Exception as e:
        print("An error occurred:", e)


def change_number_of_views_per_page(driver, num=50):
    wait = WebDriverWait(driver, 20)
    try:
        select_element = wait.until(
            EC.presence_of_element_located((By.ID, "results_per_page"))
        )

        # Create a Select object
        dropdown = Select(select_element)

        # Select the NUM option
        dropdown.select_by_visible_text(f"{num}")
        print(f"Results per page set to {num}")

    except Exception as e:
        print("An error occurred:", e)


def save_html_page(driver):
    # Get full HTML of the page
    page_source = driver.page_source

    # Save to file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"ganj_results_{timestamp}.html"

    with open(filename, "w", encoding="utf-8") as f:
        f.write(page_source)

    print(f"Page content saved to file: {filename}")


def chrome_driver_setup(url):
    # Setup Chrome options
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # Comment this line to see the browser
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")

    # Path to the ChromeDriver executable
    chrome_driver_path = r'D:\Desktop\chromedriver-win64\chromedriver.exe'

    # Set up the webdriver
    service = Service(chrome_driver_path)
    driver = webdriver.Chrome(service=service, options=chrome_options)

    # Set window size
    driver.set_window_size(1920, 1080)
    
    driver.get(url)

    return driver

def main():

    url = "https://ganj.irandoc.ac.ir/#/"
    driver = chrome_driver_setup(url)
    
    try:
        search(driver, "هوش مصنوعی")
        change_number_of_views_per_page(driver, 100)
        crawl_current_page(driver)

    except Exception as e:
        print("An error occurred:", e)

    finally:
        driver.quit()


if __name__ == "__main__":
    main()

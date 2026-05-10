from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from webdriver_manager.firefox import GeckoDriverManager
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("parser_yandex.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

DO_NOT_PARSE = ["yandex.ru", "2gis.ru", "market.yandex.ru"]

firefox_options = Options()
firefox_options.add_argument("--window-size=1920,1080")

service = Service(executable_path="geckodriver.exe")
driver = webdriver.Firefox(service=service, options=firefox_options)

def parse_links(url):
    driver.get(url=url)
    time.sleep(2)
    
    button_close = driver.find_element(By.CLASS_NAME, "DistributionButtonClose")
    try:
        button_close.click()
    except NoSuchElementException:
        logger.error("No button")
    
    a_block = driver.find_element(By.CSS_SELECTOR, "a.Link.pIVU5G7ZQkodvX3aO.Link_theme_outer.Path-Item.link.action-counter")
    logger.info("A_BLOCK FOUND")
    
    b_block = a_block.find_element(By.TAG_NAME, "b")
    logger.info("B_BLOCK FOUND")
    site_name = b_block.text.strip()
    logger.info("Text found")
    
    if site_name in DO_NOT_PARSE:
        logger.info(f"Site {site_name} is skipped")
    else:
        with open("parsed_links.txt", "a+", encoding="utf-8") as file:
            file.write(f"{site_name}\n")
            
    logger.info("Links parsing success")
    
    
    
def main():
    search_query = input("Request item: ")
    clear_query = search_query if not " " in search_query else '+'.join(search_query.split())
    logger.info(f"[+] {clear_query}")
    location = input("Location: ")
    url = f"https://yandex.ru/search/?text={search_query}+{location}&lr=213&clid=2353835"
    parse_links(url=url)


if __name__ == "__main__":
    main()
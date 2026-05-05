import time
import logging
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from webdriver_manager.firefox import GeckoDriverManager
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
import random

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("parser_yandex_maps.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def parsing(item, driver):
    item.click()
    logger.info("Item clicked")
    
    # Ждём загрузки модального окна/страницы
    WebDriverWait(driver, 5).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "a[class='card-title-view__title-link']"))
    )
    time.sleep(1)

    try:
        title = WebDriverWait(driver, 3).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[class='card-title-view__title-link']"))
        ).text.strip()
        logger.info('Title found')
    except:
        title = None
        logger.warning('⚠️ Title not found')

    try:
        phone = WebDriverWait(driver, 3).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "span[itemprop='telephone']"))
        ).text.strip()
        logger.info('Phone found')
    except:
        phone = None
        logger.warning('⚠️ Phone not found')

    try:
        site = WebDriverWait(driver, 3).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "span[class='business-urls-view__text']"))
        ).text.strip()
        logger.info('Site found')
    except:
        site = None
        logger.warning('⚠️ Site not found')

    driver.back()
    logger.info("Back to previous page")
    
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CLASS_NAME, "search-list-view__list"))
    )
    time.sleep(1)

    return title, phone, site


def scrolling_and_parsing(driver, url):
    driver.get(url)
    wait = WebDriverWait(driver, 10)
    
    batch_size = 5
    processed_urls = set()
    total_processed = 0
    empty_scrolls = 0
    MAX_EMPTY_SCROLLS = 3

    logger.info(f"🔄 Начинаем прокрутку порциями по {batch_size}...")

    while True:
        try:
            # Прокрутка
            driver.execute_script("window.scrollBy(0, 1000);")
            time.sleep(3)

            # 🔁 Всегда перепоиск контейнера и элементов
            try:
                container = wait.until(
                    EC.presence_of_element_located((By.CLASS_NAME, "search-list-view__list"))
                )
                items = container.find_elements(By.TAG_NAME, "li")
                visible_items = [i for i in items if i.is_displayed() and i.text.strip()]
            except Exception as e:
                logger.warning(f"⚠️ Не удалось получить элементы: {e}")
                visible_items = []

            if not visible_items:
                empty_scrolls += 1
                logger.info(f"⏳ Нет видимых элементов ({empty_scrolls}/{MAX_EMPTY_SCROLLS})...")
                if empty_scrolls >= MAX_EMPTY_SCROLLS:
                    logger.info("✅ Прокрутка завершена.")
                    break
                continue

            empty_scrolls = 0

            # 🔁 Собираем уникальные идентификаторы + индексы для повторного поиска
            candidates = []
            for idx, item in enumerate(visible_items):
                try:
                    link = item.find_element(By.CSS_SELECTOR, "a[href]")
                    item_url = link.get_attribute("href")
                    if item_url and item_url not in processed_urls:
                        candidates.append((idx, item_url))
                except:
                    continue

            if not candidates:
                continue

            # 🔁 Обрабатываем по ОДНОМУ элементу за итерацию
            for idx, item_url in candidates[:batch_size]:
                try:
                    # 🔁 Перепоиск контейнера и элементов перед каждым кликом
                    container = wait.until(
                        EC.presence_of_element_located((By.CLASS_NAME, "search-list-view__list"))
                    )
                    items = container.find_elements(By.TAG_NAME, "li")
                    visible_items = [i for i in items if i.is_displayed() and i.text.strip()]
                    
                    if idx >= len(visible_items):
                        continue
                        
                    fresh_item = visible_items[idx]
                    
                    processed_urls.add(item_url)
                    title, phone, site = parsing(item=fresh_item, driver=driver)
                    time.sleep(1)
                    
                    logger.info(f"→ #{total_processed + 1}: '{title[:40]}' | {phone} | {site}")
                    total_processed += 1
                    logger.info(f"✓ Элемент {total_processed} обработан")

                except Exception as e:
                    logger.error(f"✗ Ошибка в элементе: {e}")
                    # 🔁 Попытка восстановления после ошибки
                    try:
                        if driver.current_url != url:
                            driver.back()
                            wait.until(EC.presence_of_element_located((By.CLASS_NAME, "search-list-view__list")))
                            time.sleep(1)
                    except:
                        pass
                    continue

        except Exception as e:
            logger.error(f"❌ Ошибка в цикле: {e}")
            break
        
    logger.info(f"🎉 Готово! Обработано: {total_processed}")
    return total_processed

def main():
    url = 'https://yandex.ru/maps/213/moscow/search/электротехника/?ll=37.671027%2C55.743999&sll=37.669529%2C55.754944&sspn=0.749014%2C0.251023&z=11.36'

    firefox_options = Options()
    firefox_options.add_argument("--window-size=1920,1080")
    service = Service(executable_path="E:\Freelance\parser_yandex_maps\geckodriver.exe")
    driver = webdriver.Firefox(service=service, options=firefox_options)

    scrolling_and_parsing(driver=driver, url=url)


if __name__ == '__main__':
    main()
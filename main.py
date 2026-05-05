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
        logging.FileHandler("telegram_parser.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def scrolling_and_parsing(driver):
    wait = WebDriverWait(driver, 10)
    container = wait.until(
            EC.presence_of_element_located((By.CLASS_NAME, "search-list-view__list"))
        )
    logger.info("✅ Контейнер найден")
    
    batch_size = 5
    processed_items = set()
    total_processed = 0
    empty_scrolls = 0
    MAX_EMPTY_SCROLLS = 3

    logger.info(f"🔄 Начинаем прокрутку порциями по {batch_size}...")

    while True:
        try:
            driver.execute_script("window.scrollBy(0, 1000);")
            time.sleep(4)  # Ждём подгрузки

            try:
                items = container.find_elements(By.TAG_NAME, "li")
                visible_items = [i for i in items if i.is_displayed()]
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

            new_items = []
            for item in visible_items:
                item_hash = hash(item.text[:100])
                if item_hash not in processed_items:
                    new_items.append((item, item_hash))
            
            if not new_items:
                continue

            batch = new_items[:batch_size]
            logger.info(f"📦 Новая порция: {len(batch)} элементов (всего: {total_processed})")

            for idx, (item, item_hash) in enumerate(batch, 1):
                try:
                    processed_items.add(item_hash)

                    title = safe_find("._title_20enb_53") or f"untitled_{total_processed + idx}"
                    phone = safe_find("._descr_20enb_66") or ""
                    site = safe_find("._action_views_20enb_121") or ""

                    logger.info(f"→ #{total_processed + idx}: '{title[:40]}...' | {views}")

                    #TODO write parsing func

                    total_processed += 1
                    logger.info(f"✓ Элемент {total_processed} обработан")

                except Exception as e:
                    logger.error(f"✗ Ошибка в элементе: {e}")
                    continue

        except Exception as e:
            logger.error(f"❌ Ошибка в цикле: {e}")
            break
        
    logger.info(f"🎉 Готово! Обработано: {total_processed}")
    return total_processed


def main():
    url = 'https://yandex.ru/maps/213/moscow/category/electrical_products/184107066/?ll=37.581429%2C55.766542&sll=37.617700%2C55.755863&sspn=1.395264%2C0.525064&z=10'
    


if __name__ == '__main__':
    main()
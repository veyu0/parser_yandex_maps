from datetime import datetime
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
import os
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("parser_yandex_maps.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
EXPORT_FILE = "yandex_maps_russia.xlsx"

def init_excel_file(filepath, columns):
    """Создаёт Excel-файл с заголовками, если он не существует"""
    if not os.path.exists(filepath):
        df = pd.DataFrame(columns=columns)
        df.to_excel(filepath, index=False, engine='openpyxl')
        logger.info(f"📄 Создан файл: {filepath}")

def is_excluded_city(address):
    """Проверяет, нужно ли исключить запись по городу (Москва/СПб)"""
    if not address:
        return False
    
    address_lower = address.lower()
    
    # Список исключаемых городов и регионов
    excluded_patterns = [
        'москва', 'м.', 'моск. обл', 'московская обл', 'московская область',
        'санкт-петербург', 'спб', 'ленинградская обл', 'ленинградская область',
        'г. москва', 'г. санкт-петербург', 'москва, ', 'санкт-петербург, '
    ]
    
    return any(pattern in address_lower for pattern in excluded_patterns)

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

    try:
        address = WebDriverWait(driver, 3).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div[class='business-contacts-view__address-link']"))
        ).text.strip()
        logger.info('Address found')
    except:
        address = None
        logger.warning('⚠️ Address not found')

    driver.back()
    logger.info("Back to previous page")
    
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CLASS_NAME, "search-list-view__list"))
    )
    time.sleep(1)

    return title, phone, site, address


def scrolling_and_parsing(driver, url,  category):
    driver.get(url)
    wait = WebDriverWait(driver, 10)

    excel_columns = [
        'timestamp', 'category', 'city', 'title', 'phone', 'site'
    ]
    init_excel_file(EXPORT_FILE, excel_columns)
    
    processed_urls = set()
    total_processed = 0
    empty_scrolls = 0
    MAX_EMPTY_SCROLLS = 3
    BATCH_SIZE = 5

    logger.info(f"🔄 Начинаем прокрутку порциями по {BATCH_SIZE}...")

    while True:
        # 🔁 1. Перепоиск контейнера и элементов
        try:
            list_container = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "ul.search-list-view__list"))
            )
            items = list_container.find_elements(By.TAG_NAME, "li")
            visible_items = [i for i in items if i.is_displayed() and i.text.strip()]
        except Exception as e:
            logger.warning(f"⚠️ Не удалось получить элементы: {e}")
            visible_items = []

        # 🔁 2. Собираем кандидатов
        candidates = []
        for idx, item in enumerate(visible_items):
            try:
                link = item.find_element(By.CSS_SELECTOR, "a[href*='/maps/org/']")
                item_url = link.get_attribute("href")
                if item_url and item_url not in processed_urls:
                    candidates.append((idx, item_url))
            except:
                continue

        # 🔁 3. Если нет новых элементов — скроллим или завершаем
        if not candidates:
            empty_scrolls += 1
            logger.info(f"⏳ Нет новых элементов ({empty_scrolls}/{MAX_EMPTY_SCROLLS})...")
            if empty_scrolls >= MAX_EMPTY_SCROLLS:
                logger.info("✅ Прокрутка завершена.")
                break
            
            # 🔄 СКРОЛЛ через универсальную функцию
            scrolled = _scroll_list_container(driver)
            time.sleep(2.5)
            continue

        empty_scrolls = 0
        
        # 🔁 4. Берём батч
        batch = candidates[:BATCH_SIZE]
        logger.info(f"📦 Новая порция: {len(batch)} элементов (всего: {total_processed})")

        # 🔁 5. Обрабатываем каждый элемент с перепоиском
        for batch_idx, (item_index, item_url) in enumerate(batch, 1):
            try:
                list_container = wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "ul.search-list-view__list"))
                )
                items = list_container.find_elements(By.TAG_NAME, "li")
                visible_items = [i for i in items if i.is_displayed() and i.text.strip()]
                
                if item_index >= len(visible_items):
                    continue
                    
                fresh_item = visible_items[item_index]
                processed_urls.add(item_url)
                title, phone, site, address = parsing(item=fresh_item, driver=driver)

                if is_excluded_city(address):
                    logger.info(f"⏭ Пропущено (Москва/СПб): '{title[:40] if title else 'N/A'}' | {address}")
                    continue  # ↩️ Переходим к следующему элементу

                logger.info(f"→ #{total_processed + batch_idx}: '{title[:40]}' | {phone} | {site}")
                
                record = {
                    'timestamp': datetime.utcnow(),
                    'category': category,
                    'city': address,
                    'title': title,
                    'phone': phone,
                    'site': site
                }
                
                # 💾 Сохраняем СРАЗУ после парсинга
                if append_to_excel(EXPORT_FILE, record):
                    logger.info(f"→ #{total_processed + batch_idx}: '{title[:40]}' | {phone} | {site} ✅")
                else:
                    logger.warning(f"⚠️ Не удалось сохранить запись #{total_processed + batch_idx}")

            except Exception as e:
                logger.error(f"✗ Ошибка в элементе: {e}")
                try:
                    if driver.current_url != url:
                        driver.back()
                        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "ul.search-list-view__list")))
                        time.sleep(1)
                except:
                    pass
                continue

        total_processed += len(batch)
        logger.info(f"✓ Батч завершён. Всего обработано: {total_processed}")
        
        # 🔄 СКРОЛЛ после батча
        scrolled = _scroll_list_container(driver)
        time.sleep(2.5)

    logger.info(f"🎉 Готово! Обработано: {total_processed}")
    return total_processed

def _scroll_list_container(driver, scroll_amount=600):
    """
    Универсальная прокрутка: находит первый скроллящийся родитель 
    у контейнера списка и скроллит его.
    Возвращает True, если скролл выполнен, False если достигнут конец.
    """
    try:
        # JS-скрипт: находит скроллящийся контейнер и прокручивает его
        result = driver.execute_script(f"""
            // Находим ul.search-list-view__list
            var list = document.querySelector('ul.search-list-view__list');
            if (!list) return {{found: false, reason: 'list not found'}};
            
            // Ищем первый скроллящийся родитель (включая сам list)
            var el = list;
            while (el && el !== document.documentElement) {{
                var scrollable = el.scrollHeight > el.clientHeight;
                var hasOverflow = window.getComputedStyle(el).overflowY === 'auto' || 
                                  window.getComputedStyle(el).overflowY === 'scroll';
                if (scrollable && hasOverflow) {{
                    var oldTop = el.scrollTop;
                    el.scrollTop += {scroll_amount};
                    var newTop = el.scrollTop;
                    return {{
                        found: true, 
                        scrolled: newTop > oldTop,
                        scrollTop: newTop,
                        scrollHeight: el.scrollHeight,
                        clientHeight: el.clientHeight,
                        tagName: el.tagName,
                        className: el.className
                    }};
                }}
                el = el.parentElement;
            }}
            
            // Если не нашли скроллящийся контейнер — пробуем скроллить окно
            window.scrollBy(0, {scroll_amount});
            return {{found: false, reason: 'fallback to window'}};
        """)
        
        if result.get('found'):
            if result.get('scrolled'):
                logger.debug(f"📜 Скролл: {result.get('tagName')}.{result.get('className', '')[:30]} | scrollTop: {result.get('scrollTop')}/{result.get('scrollHeight')}")
                return True
            else:
                logger.debug("🛑 Достигнут конец скролл-контейнера")
                return False
        else:
            logger.debug(f"🔄 Fallback: {result.get('reason')}")
            return True  # Окно проскроллили
            
    except Exception as e:
        logger.warning(f"⚠️ Ошибка при скролле: {e}")
        # Fallback: скроллим окно
        driver.execute_script(f"window.scrollBy(0, {scroll_amount});")
        return True

def append_to_excel(filepath, data_dict):
    """Добавляет одну строку в Excel-файл"""
    try:
        # Читаем существующий файл или создаём новый
        if os.path.exists(filepath):
            df_existing = pd.read_excel(filepath, engine='openpyxl')
            df_new = pd.DataFrame([data_dict])
            df_combined = pd.concat([df_existing, df_new], ignore_index=True)
        else:
            df_combined = pd.DataFrame([data_dict])
        
        # Сохраняем с перезаписью
        df_combined.to_excel(filepath, index=False, engine='openpyxl')
        logger.debug(f"💾 Запись сохранена: {data_dict.get('title', 'N/A')[:30]}...")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения в Excel: {e}")
        return False
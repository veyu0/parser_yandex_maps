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
EXPORT_FILE = "yandex_maps_saint_p.xlsx"

def init_excel_file(filepath, columns):
    """Создаёт Excel-файл с заголовками, если он не существует"""
    if not os.path.exists(filepath):
        df = pd.DataFrame(columns=columns)
        df.to_excel(filepath, index=False, engine='openpyxl')
        logger.info(f"📄 Создан файл: {filepath}")

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
            EC.presence_of_element_located((By.CSS_SELECTOR, "span[class='business-contacts-view__address-link']"))
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


def scrolling_and_parsing(driver, url,  category, city):
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
    
def main():
    # 🔧 Настройте параметры поиска
    SEARCH_CATEGORY = "Электротехника"
    #SEARCH_CITY = "Санкт-Петербург"
    
    # Формируем URL (адаптируйте под ваш формат)
    url = f'https://yandex.ru/maps/?ll=90.174499%2C52.732474&mode=search&sctx=ZAAAAAgBEAAaKAoSCQiPNo5Y4FhAEUsgJXZt2U5AEhIJAAAAAADDbkARsHPTZpwcU0AiBgABAgMEBSgKOABAkE5IAWoCcnWdAc3MzD2gAQCoAQC9ATKK1JnCAYQB6cyQptcG4NCWtb4CxP2kydUFuN6D7wPGvfvoZKyg544EsITtnewB3OXTqgT71vi2Bq%2Fl1IAE7Of44ASu%2FJDpA9%2FfntR34oG0%2FJwDmefQmATEjsmDBOOI0YMEv7LjstABie%2BQzQbT0PmMqQKysbjvA%2FrswPYDrvfr4gT4reP8BIuR9dsGggIc0K3Qu9C10LrRgtGA0L7RgtC10YXQvdC40LrQsIoCCTE4NDEwNzA2NpICAJoCDGRlc2t0b3AtbWFwc6oC9gE0MDUzNjc0ODQ5MCwyMzkzODk5MTE0MzEsNzI1NzY2MjAwLDMwOTI0ODYwNDIsODA0MDI2MTUyNDYsMjUxODc1NTgzMCwzNjYzNjU3MDk2LDU4MDU3Nzg5NSw4MDU1NTEwNjQsMTI2OTgzMDU2MzgsNDQ2NjcyNzkzNywxNjY4MTAwNzI2MCwyNTc1MTc5NTU1LDQ2MzkwNDU2MjMsMjExNzMzMTczMTgxLDk4NDU5NzAyNzE5LDIwMzA2NzY2MjQsODMwODkxOTYwLDE2NjQxNTU2MzU5LDQ4NTk1NDQ4ODUsMTMxNzc3MjMzMSw4MzA4OTE5MzPaAigKEgl4O8Jpwe9NQBFNirIY54tJQBISCXCVJxB2mXBAEfMXHwt201hA4AIB&sll=90.174499%2C52.732474&sspn=265.591324%2C97.092270&text=%D0%AD%D0%BB%D0%B5%D0%BA%D1%82%D1%80%D0%BE%D1%82%D0%B5%D1%85%D0%BD%D0%B8%D0%BA%D0%B0&z=2.89'

    firefox_options = Options()
    firefox_options.add_argument("--window-size=1920,1080")
    
    service = Service(executable_path="E:\\Freelance\\parser_yandex_maps\\geckodriver.exe")
    driver = webdriver.Firefox(service=service, options=firefox_options)

    try:
        scrolling_and_parsing(
            driver=driver, 
            url=url,
            category=SEARCH_CATEGORY,
        )
    finally:
        driver.quit()
        logger.info("🔚 Браузер закрыт")

    firefox_options = Options()
    firefox_options.add_argument("--window-size=1920,1080")
    
    service = Service(executable_path="E:\\Freelance\\parser_yandex_maps\\geckodriver.exe")
    driver = webdriver.Firefox(service=service, options=firefox_options)
    SEARCH_CATEGORY = "Электроизоляционные%20материалы"
    SEARCH_CITY = "Санкт-Петербург"
    
    # Формируем URL (адаптируйте под ваш формат)
    url = f'https://yandex.ru/maps/?ll=89.355317%2C49.455914&mode=search&sctx=ZAAAAAgBEAAaKAoSCdKL2v0qi1ZAEc2VQbXBXUpAEhIJbhea67QJZEARuRluwOdFWEAiBgABAgMEBSgKOABA4QFIAWoCcnWdAc3MzD2gAQCoAQC9AcHBiqPCAYIBspzM%2BwPNjNmCBJ%2FPhv0D2rKT%2BAWfoMeTBZCo0ZkE5oKX0XygmpW52gSo2ojKqAPfifv3A86G44ME07HY0gSblYWOBIaO8ZEE9cWc%2FRPkkfbkxAaAxvmQBJ7w1aX7Be27nfwD%2FqLRjQbjl63JBIXrgtMGt8ra4gSclYTWxwTnyeDiA4ICOdCt0LvQtdC60YLRgNC%2B0LjQt9C%2B0LvRj9GG0LjQvtC90L3Ri9C1INC80LDRgtC10YDQuNCw0LvRi4oCAJICAJoCDGRlc2t0b3AtbWFwc9oCKAoSCccy%2FRLx3lVAEX9bAdYcJElAEhIJ%2BptQiIATWkARdEUXPjylUEDgAgE%3D&sll=89.355317%2C49.455914&sspn=181.605065%2C112.309178&text=%D0%AD%D0%BB%D0%B5%D0%BA%D1%82%D1%80%D0%BE%D0%B8%D0%B7%D0%BE%D0%BB%D1%8F%D1%86%D0%B8%D0%BE%D0%BD%D0%BD%D1%8B%D0%B5%20%D0%BC%D0%B0%D1%82%D0%B5%D1%80%D0%B8%D0%B0%D0%BB%D1%8B&z=2.71'

    try:
        scrolling_and_parsing(
            driver=driver, 
            url=url,
            category=SEARCH_CATEGORY,
        )
    finally:
        driver.quit()
        logger.info("🔚 Браузер закрыт")

    firefox_options = Options()
    firefox_options.add_argument("--window-size=1920,1080")
    
    service = Service(executable_path="E:\\Freelance\\parser_yandex_maps\\geckodriver.exe")
    driver = webdriver.Firefox(service=service, options=firefox_options)
    SEARCH_CATEGORY = "Электроустановочная%20продукция"
    SEARCH_CITY = "Санкт-Петербург"
    
    # Формируем URL (адаптируйте под ваш формат)
    url = "https://yandex.ru/maps/?ll=84.185228%2C39.246912&mode=search&sctx=ZAAAAAgBEAAaKAoSCZ%2Btg4O9VlZAEe%2Fk02NbukhAEhIJiV5GsVyzZkARIqmFkskTXEAiBgABAgMEBSgKOABAkE5IAWoCcnWdAc3MzD2gAQCoAQC9AcnCTmTCAYUB6MTLjaoF2o%2B2j5UG1NPD6APykoKsgwaH5IaYB%2FPmgqgEgtKNmATM%2Bs%2F%2BMvPqsvkDj83ArPQEhsC44QPu4bLdA4XurZYElOOP1ASWn9XuA6686JME6afEnQST8fqX9AKLuIaLBP6soeS%2FAaDqhesD%2FZHRpQaHoYjZ3wL5o%2F33hQbN0suOBIICOdCt0LvQtdC60YLRgNC%2B0YPRgdGC0LDQvdC%2B0LLQvtGH0L3QsNGPINC%2F0YDQvtC00YPQutGG0LjRj4oCCTE4NDEwNzA1OJICAJoCDGRlc2t0b3AtbWFwc6oCxwE0MDUzNjc0ODQ5MCw1MTA1NzMyMDkxLDIwMDQ4OTMwNzIsMTk0MDg2MTU4NTY3LDI0MzcyNTcyODEzLDM5ODM3NzY4ODksNDQxNjE1NjIxNCwxMzYyMzkyNjY4OTQsNTM0NzM4MDIyMTcsNDA0MTM0NjUwNCw0MTk1MDU0MTY3LDE1OTIwMTY4MjI2LDExNDk3MzgxMTA2NSwxNzI0ODgzODk0MywxNDE3NTUwMzI2LDIyMzU5NzA3MzE1MSw5MTgxMTExMDI52gIoChIJTpKumXzDUkAR%2BNeFu3jHLUASEglGtB1TN%2B9xQBGqlte%2B%2FgFkQOACAQ%3D%3D&sll=84.185228%2C39.246912&sspn=124.902680%2C90.392277&text=%D0%AD%D0%BB%D0%B5%D0%BA%D1%82%D1%80%D0%BE%D1%83%D1%81%D1%82%D0%B0%D0%BD%D0%BE%D0%B2%D0%BE%D1%87%D0%BD%D0%B0%D1%8F%20%D0%BF%D1%80%D0%BE%D0%B4%D1%83%D0%BA%D1%86%D0%B8%D1%8F&z=3.25"

    try:
        scrolling_and_parsing(
            driver=driver, 
            url=url,
            category=SEARCH_CATEGORY,
        )
    finally:
        driver.quit()
        logger.info("🔚 Браузер закрыт")

    firefox_options = Options()
    firefox_options.add_argument("--window-size=1920,1080")
    
    service = Service(executable_path="E:\\Freelance\\parser_yandex_maps\\geckodriver.exe")
    driver = webdriver.Firefox(service=service, options=firefox_options)
    SEARCH_CATEGORY = "Кабель%20и%20провод"
    SEARCH_CITY = "Санкт-Петербург"
    
    # Формируем URL (адаптируйте под ваш формат)
    url = "https://yandex.ru/maps/?ll=73.476711%2C47.377180&mode=search&sctx=ZAAAAAgBEAAaKAoSCcWPMXctRFJAESic3VomUyJAEhIJem8MAUBCZEAR%2FirAd5tCZEAiBgABAgMEBSgKOABAkE5IAWoCcnWdAc3MzD2gAQCoAQC9AXHNsB3CAQXp%2FPvaT4ICHNC60LDQsdC10LvRjCDQuCDQv9GA0L7QstC%2B0LSKAgkxODQxMDcwMzKSAgCaAgxkZXNrdG9wLW1hcHOqAu8BMjE4ODM1OTg1MDM1LDUxNzc4Mjg4MjgyLDE2NzE0MzIzNzE2NSwxNzI1OTI1MTA5MSw3Mjk3ODQyMDQzLDQwNzA0NDI3MjcsNDk0ODAzNzc3OTMsNzkxMjkzMjc1MTcsNDIzMTQ4MjkwNiwyMjM4Njg3MTA2NjIsNDA0MTI2OTA0MCwxMjY5ODMwNTYzOCwxNzgxNDU4MDA4MywxMTY1NjI0NDY2OTAsMTU4NjkxNjA1NTksMTM4ODk1ODQyNjUsMjQ1MjMzOTg1MjU3LDE2NjQxNTU2MzU5LDc1MjQwNjk3ODQsMTU4Njk2MjQxNzM%3D&sll=-12.981298%2C45.477544&sspn=154.842815%2C102.355776&text=%D0%BA%D0%B0%D0%B1%D0%B5%D0%BB%D1%8C%20%D0%B8%20%D0%BF%D1%80%D0%BE%D0%B2%D0%BE%D0%B4&z=2.94"

    try:
        scrolling_and_parsing(
            driver=driver, 
            url=url,
            category=SEARCH_CATEGORY,
        )
    finally:
        driver.quit()
        logger.info("🔚 Браузер закрыт")

    firefox_options = Options()
    firefox_options.add_argument("--window-size=1920,1080")
    
    service = Service(executable_path="E:\\Freelance\\parser_yandex_maps\\geckodriver.exe")
    driver = webdriver.Firefox(service=service, options=firefox_options)
    SEARCH_CATEGORY = "Светотехника"
    SEARCH_CITY = "Санкт-Петербург"
    
    # Формируем URL (адаптируйте под ваш формат)
    url = "https://yandex.ru/maps/org/svetotehnika/43090662950/?ll=82.663004%2C42.772378&mode=search&sctx=ZAAAAAgBEAAaKAoSCS6p2m6CXlJAEUdaKm9HsEdAEhIJgbIpV%2FhaY0ARSkG3lzQZWUAiBgABAgMEBSgKOABAkE5IAWoCcnWdAc3MzD2gAQCoAQC9AbwtVJnCAYUBq4DW9pgBpqydw6ABqMXbqgTH7prcc4vIwOuEBMvvgIAE44jRgwT4gbOhugWD7eez2QKigduMBfis4qkEs5iZpgaM2%2F23%2BgGVjYn0BaD6h%2BHgBc2cyNoEhMLKiQSntKD3BK2kmIYFkuG6yQS2trjEjQLis5W%2BBIC1tKEEgKythQSCvNLIBIICGNGB0LLQtdGC0L7RgtC10YXQvdC40LrQsIoCEzE4NDEwNjg5OCQxODQxMDcxODKSAgCaAgxkZXNrdG9wLW1hcHOqAtQCMTc3MTMxMTQ2NDcsMTcyNTY1NjY0ODcsNTE0NjAyOTQ3OCwzNTM5NzMwNTAxMCw4OTMyMjU4NTY4MSwxODc1MzU5NTIxNTIsMTg5MTU0NzQ1OSwyNTE4NzU1ODMwLDE3MjY5ODc3ODQ4LDEzODQwNjg1NzMsNDE2ODU2Njc3Myw0MTk0NjMwMTMzLDM1NTA1MzQ5NzAwLDExMDAwOTU2MTYyOCwxNzIyMzMyNjIwNyw3NDk1NTMwNTg1LDI0MjI3NDk4MjY5Miw5Njg2MDQxNTIxNCwxMDA4ODU5ODc5MDksNDQyODk0NTE2MSw5NzE1MTUwNzQyNSw4MDU1NTEwNjQsNzE5NTA4NDI0NTQsMzY2Mzc2OTY5NSwyMDk5NDM5OTQ2NDAsMjM2NDU4NzE1NTk0LDI3MjkzNTkwNCwzOTgzNzcxMDA0LDIxNjAwOTYxNTA1NdoCKAoSCWBvYkhOYEVAEaYXXkjdYkVAEhIJyH2rdeKRX0ARQgsqJqZaYUDgAgE%3D&sll=82.663004%2C42.772378&sspn=126.279447%2C138.730551&text=%D1%81%D0%B2%D0%B5%D1%82%D0%BE%D1%82%D0%B5%D1%85%D0%BD%D0%B8%D0%BA%D0%B0&z=2.36"
    try:
        scrolling_and_parsing(
            driver=driver, 
            url=url,
            category=SEARCH_CATEGORY,
        )
    finally:
        driver.quit()
        logger.info("🔚 Браузер закрыт")

    firefox_options = Options()
    firefox_options.add_argument("--window-size=1920,1080")
    
    service = Service(executable_path="E:\\Freelance\\parser_yandex_maps\\geckodriver.exe")
    driver = webdriver.Firefox(service=service, options=firefox_options)
    SEARCH_CATEGORY = "Электромонтажные%20работы"
    SEARCH_CITY = "Санкт-Петербург"
    
    # Формируем URL (адаптируйте под ваш формат)
    url = "https://yandex.ru/maps/?ll=70.240150%2C9.162402&mode=search&sctx=ZAAAAAgBEAAaKAoSCXrejQWFLT5AETATRUjdYkVAEhIJAyZw6%2B7ubEAR7KF9rGBXYUAiBgABAgMEBSgKOABAkE5IAWoCcnWdAc3MzD2gAQCoAQC9AZ5Nn9DCAYoBopLO1cYFtsCJsgTEpMPwWfayzKkGntKEtbsF5KGv3Qan2Y6wtASonv28mAS79%2BSrBpuGpIm6A7Ww4fbIA4Kw59aBBaDJrr6TA8OKjoSIBejW%2FvUDprGSgZID55%2B%2F8QO2w7HargXet%2FOTBbO54oYEuLSVnRrjpZrshQXkhNKVoQGAn4q%2BBtS9s4IEggIt0Y3Qu9C10LrRgtGA0L7QvNC%2B0L3RgtCw0LbQvdGL0LUg0YDQsNCx0L7RgtGLigIJMTg0MTA3NjU1kgIAmgIMZGVza3RvcC1tYXBzqgI%2BMTU3NzA3NTUxMjk3LDE0MTIxMDE2NzYxMywxNDc4NzA3MDM0OTQsOTYzMzI4MDQ2MjMsMTIyMDczOTY1OTXaAigKEgnL7snDQrlDwBGbI%2BdaJlMiQBISCb03hgAgkXJAEchK5VCzQmRA4AIB&sll=70.240150%2C9.162402&sspn=297.070313%2C162.081478&text=%D1%8D%D0%BB%D0%B5%D0%BA%D1%82%D1%80%D0%BE%D0%BC%D0%BE%D0%BD%D1%82%D0%B0%D0%B6%D0%BD%D1%8B%D0%B5%20%D1%80%D0%B0%D0%B1%D0%BE%D1%82%D1%8B&z=2"

    try:
        scrolling_and_parsing(
            driver=driver, 
            url=url,
            category=SEARCH_CATEGORY,
        )
    finally:
        driver.quit()
        logger.info("🔚 Браузер закрыт")

    firefox_options = Options()
    firefox_options.add_argument("--window-size=1920,1080")
    
    service = Service(executable_path="E:\\Freelance\\parser_yandex_maps\\geckodriver.exe")
    driver = webdriver.Firefox(service=service, options=firefox_options)
    SEARCH_CATEGORY = "Монтаж%20систем%20освещения"
    SEARCH_CITY = "Санкт-Петербург"
    
    # Формируем URL (адаптируйте под ваш формат)
    url = "https://yandex.ru/maps/?ll=52.877167%2C9.162402&mode=search&sctx=ZAAAAAgBEAAaKAoSCZoIG55ej1FAESic3VomUyJAEhIJvTeGACCRckAR%2FirAd5tCZEAiBgABAgMEBSgKOABAolNIAWoCcnWdAc3MzD2gAQCoAQC9Ae7VZNfCAQz466O84AXN%2B7KasQSCAizQvNC%2B0L3RgtCw0LYg0YHQuNGB0YLQtdC8INC%2B0YHQstC10YnQtdC90LjRj4oCAJICAJoCDGRlc2t0b3AtbWFwc6oCqwE4MDU1NTEwNjQsNTA4Mzg4MDUxOTQsMjE1ODcwMTc1MTQzLDUxODEwMTc3MDgsMTUzNzk0NjEwNDY1LDE3MjU2NTY2NDg3LDQ2MjkyMDY1NTE2LDIyNDQ5NzYwMDMxMSwyMzY0NTg3MTU1OTQsMTM2NzYwNDM1NjczLDE3NjkzMjYyODg2OCw5Njg2MDQxNTIxNCw2MTY1MjIwNjc2MSwxOTU5OTkwMzMxNzk%3D&sll=52.877167%2C9.162402&sspn=297.070313%2C162.081478&text=%D0%BC%D0%BE%D0%BD%D1%82%D0%B0%D0%B6%20%D1%81%D0%B8%D1%81%D1%82%D0%B5%D0%BC%20%D0%BE%D1%81%D0%B2%D0%B5%D1%89%D0%B5%D0%BD%D0%B8%D1%8F&z=2"
    try:
        scrolling_and_parsing(
            driver=driver, 
            url=url,
            category=SEARCH_CATEGORY,
        )
    finally:
        driver.quit()
        logger.info("🔚 Браузер закрыт")

    firefox_options = Options()
    firefox_options.add_argument("--window-size=1920,1080")
    
    service = Service(executable_path="E:\\Freelance\\parser_yandex_maps\\geckodriver.exe")
    driver = webdriver.Firefox(service=service, options=firefox_options)
    SEARCH_CATEGORY = "Строительство%20и%20обслуживание%20электросетей"
    SEARCH_CITY = "Санкт-Петербург"
    
    # Формируем URL (адаптируйте под ваш формат)
    url = "https://yandex.ru/maps/?ll=24.636277%2C9.162402&mode=search&sctx=ZAAAAAgBEAAaKAoSCbIQHQJHcEpAESic3VomUyJAEhIJvTeGACCRckAR%2FirAd5tCZEAiBgABAgMEBSgKOABAkE5IAWoCcnWdAc3MzD2gAQCoAQC9ARpkBMXCAX%2Fjj%2FWJBPbPsuwDwfCD7gPWv%2BuaBIuDn%2B4DwPrRggS4urWTBPPAq5sE9%2FbOlQSvxPa9DYfOxYkE4YOU5APSkoedBMDHqOPmA%2FKvqfwDk9DI6wPY4p%2FgA9Celf8EkayY4gPypfbhA8vlsJYE6byWnQTP2N7ABKmgs94DvKSF2vsEggJP0YHRgtGA0L7QuNGC0LXQu9GM0YHRgtCy0L4g0Lgg0L7QsdGB0LvRg9C20LjQstCw0L3QuNC1INGN0LvQtdC60YLRgNC%2B0YHQtdGC0LXQuYoCEzE4NDEwNzA3NiQxODQxMDgzMTGSAgCaAgxkZXNrdG9wLW1hcHOqArkCNzQxODUzOTU0NDksNjkzMjEwMzE0NTksNjAwMjA2Myw2ODI0MzU0MjQ4NSw5MDY2NjA1NzY0LDYwMDI2MjMsMzI3Mjg4MDM3Myw5MDY3MDIyNjYxLDIyMjk0NjAxMTM2LDc1ODEyODUzNTc0LDI2MDM0ODM1NTIsMjQ0Mzg4MDQyMTgyLDE4OTU4NjE4MTE0MCwyMDY5NTM0NDUzNjAsMzI3MzA3MTI4NiwxMTgxNjU2ODAxNzUsNTM0NzIyNTkxNDUsODM3NjUzNDc0OTksMjE3OTUwNzU3NzQ4LDYwODcyMjMwOTIsMjU2MzMyNjcwNyw0NDMxMDg1MDYwLDMzNDE0MDU1MTA5LDEyMTAwNTc4NDA5MSw0MDg2NTQyMTMwNywyODcyMDAxMTcwOCw0NzQ2MTE2OTQzMbACAdoCKAoSCTcZVYZxPUFAEZsj51omUyJAEhIJem8MAUBCZEARyErlULNCZEDgAgE%3D&sll=92.136277%2C9.162402&sspn=162.070313%2C162.081478&text=%D1%81%D1%82%D1%80%D0%BE%D0%B8%D1%82%D0%B5%D0%BB%D1%8C%D1%81%D1%82%D0%B2%D0%BE%20%D0%B8%20%D0%BE%D0%B1%D1%81%D0%BB%D1%83%D0%B6%D0%B8%D0%B2%D0%B0%D0%BD%D0%B8%D0%B5%20%D1%8D%D0%BB%D0%B5%D0%BA%D1%82%D1%80%D0%BE%D1%81%D0%B5%D1%82%D0%B5%D0%B9&z=2"

    try:
        scrolling_and_parsing(
            driver=driver, 
            url=url,
            category=SEARCH_CATEGORY,
        )
    finally:
        driver.quit()
        logger.info("🔚 Браузер закрыт")

    firefox_options = Options()
    firefox_options.add_argument("--window-size=1920,1080")
    
    service = Service(executable_path="E:\\Freelance\\parser_yandex_maps\\geckodriver.exe")
    driver = webdriver.Firefox(service=service, options=firefox_options)
    SEARCH_CATEGORY = "Автоматизация%20инженерных%20систем"
    SEARCH_CITY = "Санкт-Петербург"
    
    # Формируем URL (адаптируйте под ваш формат)
    url = "https://yandex.ru/maps/?ll=68.509399%2C9.162402&mode=search&sctx=ZAAAAAgBEAAaKAoSCQiPNo5Y4FhAEUsgJXZt2U5AEhIJAAAAAADDbkARsHPTZpwcU0AiBgABAgMEBSgKOABAkE5IAWoCcnWdAc3MzD2gAQCoAQC9Af1c0W3CAYoB6KfZtIUHrI6A9FLB%2BNeJBNyJyO0F7afbmQSo3t6Z0APiyNjvA6Pb5JeJA4K01%2BPxBd67j6GhBPD%2FzeDmBdbcjeEDi6%2F26QW67ouFBMn60qaXAtSCqcHdA%2BT%2F%2B7nbBJn3nuYDxoaS206GpOL9ogKgrYKzBIOm9e2BBOP0iJPCBNjk%2F6AF4cvGmNkGggI80LDQstGC0L7QvNCw0YLQuNC30LDRhtC40Y8g0LjQvdC20LXQvdC10YDQvdGL0YUg0YHQuNGB0YLQtdC8igIAkgIAmgIMZGVza3RvcC1tYXBzqgI%2BMjM3MTQzNTU4MDgwLDIyNDQ5NzYwMDMxMSwyMTUzMDY5ODY3MzcsMTc0NTcwOTA0MzUwLDQxOTUwODIwNDc%3D&sll=68.509399%2C9.162402&sspn=492.187500%2C162.081478&text=%D0%B0%D0%B2%D1%82%D0%BE%D0%BC%D0%B0%D1%82%D0%B8%D0%B7%D0%B0%D1%86%D0%B8%D1%8F%20%D0%B8%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D0%BD%D1%8B%D1%85%20%D1%81%D0%B8%D1%81%D1%82%D0%B5%D0%BC&z=2"
    try:
        scrolling_and_parsing(
            driver=driver, 
            url=url,
            category=SEARCH_CATEGORY,
        )
    finally:
        driver.quit()
        logger.info("🔚 Браузер закрыт")

    firefox_options = Options()
    firefox_options.add_argument("--window-size=1920,1080")
    
    service = Service(executable_path="E:\\Freelance\\parser_yandex_maps\\geckodriver.exe")
    driver = webdriver.Firefox(service=service, options=firefox_options)
    SEARCH_CATEGORY = "Стройматериалы"
    SEARCH_CITY = "Санкт-Петербург"
    
    # Формируем URL (адаптируйте под ваш формат)
    url = "https://yandex.ru/maps/?ll=95.562479%2C54.231237&mode=search&sctx=ZAAAAAgBEAAaKAoSCV5nQ%2F6ZIFFAESic3VomUyJAEhIJAAAAAADDfkAR%2FirAd5tCZEAiBgABAgMEBSgKOABAkE5IAWoCcnWdAc3MzD2gAQCoAQC9AW5TDJzCAYYBkt3c5APokO6HBd7Ci8wNwPnP8QOj5onU5gWt4P2qBtO0444E19%2Bp5oEBmurzwAbpv5ua5QWCvejSBquqtus4hc3pscEE7YibjwWv%2BsibVpzzp6%2BDAdH%2BkbbIAbaNq9OTBLWots8E1aKQrNUGoNvmkgaIycGYBI2wx4QE5Iq9jJQE2NfQngSCAhzRgdGC0YDQvtC50LzQsNGC0LXRgNC40LDQu9GLigKuATE4NDEwNzc1MyQxODE2NTIyNzE0NjYkMTQ5NDA5NDA4NTIkMTg0MTA3NzU1JDE4NDEwNzY5OSQxODQxMDc3NTkkMTg0MTA3NjkxJDE4NDEwNzc2NSQxODQxMDc3NTckMTg0MTA3NzYzJDE4NDEwNzcwMSQxODQxMDc2ODEkMTg0MTA3NzYxJDE4NDEwNzcyMSQxODQxMDc2NzEkMTg0MTA3NzM3JDE4NDEwNzY2NZICAJoCDGRlc2t0b3AtbWFwc6oCnQM0NjYyMDA3NzgwMCwxNzU4MTEyNjM3MDUsMzYxODE0NTQ1Myw2MDAzMTIwLDE3ODM1NzIyMjU5NSw3NjUxMzM0MzM3MywyMDQ3NTYwMTc3OCw2MDAxODc1LDkzNTc0NTE3NDQ4LDQzNTk1OTc1NzIsNjAwMjAxNiwyMjk3NzIyNzgxMTgsMzg5MTc0NTMxLDE0MzE0MTc0MDkxMyw1ODYyODEzMjA5MywxOTQ4NjQ3MjI0NzIsMzg5OTg3NDc3NywxNTU5MDE4MjEyMjksOTMwMjk4MzAwODksNDQ4MzQyOTAyOTcsNzAyMzkwMTE4NjUsMjE4NTUwOTMxMSwyMjY2MjY5MDYyMDMsMTAzMzQ2MjAyNzksNjkyMDg5MDAyNTIsODY5OTI4NDk0OTksMjI4MDQ4OTk1NzQyLDM4NjgyMjY0NTA2LDYzMTc0Njk5NDY4LDE2MTYyNzI2Nzk4Miw2ODcxMzE1MTQ0MiwxMzU5NjE5MDIyNywxNDcxNDA3Njk1NjQsMTE5NTk4ODUzNTk4LDExMjgzNzEyMDg2N9oCKAoSCRd1rb1P1TFAEQLgZgvPHUpAEhIJiSgmbwCaZUARKX2dq9gWUEDgAgE%3D&sll=95.562479%2C54.231237&sspn=172.812553%2C61.896549&text=%D1%81%D1%82%D1%80%D0%BE%D0%B9%D0%BC%D0%B0%D1%82%D0%B5%D1%80%D0%B8%D0%B0%D0%BB%D1%8B&z=3.51"
    try:
        scrolling_and_parsing(
            driver=driver, 
            url=url,
            category=SEARCH_CATEGORY,
        )
    finally:
        driver.quit()
        logger.info("🔚 Браузер закрыт")

    firefox_options = Options()
    firefox_options.add_argument("--window-size=1920,1080")
    
    service = Service(executable_path="E:\\Freelance\\parser_yandex_maps\\geckodriver.exe")
    driver = webdriver.Firefox(service=service, options=firefox_options)
    SEARCH_CATEGORY = "Строительные%20гипермаркеты"
    SEARCH_CITY = "Санкт-Петербург"
    
    # Формируем URL (адаптируйте под ваш формат)
    url = "https://yandex.ru/maps/org/komfort/165418434379/?ll=107.994659%2C22.734181&mode=search&sctx=ZAAAAAgBEAAaKAoSCfRr66f%2F41dAEQVQjCyZHUtAEhIJiSgmbwCaZUAReSEdHsLyTkAiBgABAgMEBSgKOABAkE5IAWoCcnWdAc3MTD2gAQCoAQC9Afpu8nvCAYgB2Nqj%2FQPL%2FtOd6ATPiNi3Bo6ks5XxA%2BCSi5gEzbaUhQrmqsXSnQHBw9j2vQaE1pPwugXLqvf95ALbyfTiBc%2Fj4NMEzerI7wWkls3lvQXinpGxBpTJ%2Fb9H5Iq9jJQEsOCt4gXttafLhQKCvejSBvvkqL4UsZ7uw54GuP3%2FmPgE1YWz%2FQOC6t2MBIICMdGB0YLRgNC%2B0LjRgtC10LvRjNC90YvQtSDQs9C40L%2FQtdGA0LzQsNGA0LrQtdGC0YuKAgsxNDk0MDk0MDg1MpICAJoCDGRlc2t0b3AtbWFwc6oCggIyNTYzNjI3NzIwLDc2NTEzMzQzMzczLDE4OTUyODk3ODk2Nyw2MDAyMDE2LDY4NzEzMTUxNDQyLDIyOTc3MjI3ODExOCwzODkxNzQ1MzEsMTQ3MTQwNzY5NTY0LDM4NjgyMjY0NTA2LDE1NDQ3ODY2MTI2OSw0NjYyMDA3NzgwMCwzODk5ODc0Nzc3LDg2OTkyODQ5NDk5LDcwMjM5MDExODY1LDM0NTg5MjI2NiwxNDMxNDE3NDA5MTMsODcxODI5NTE1NDUsMTk0ODY0NzIyNDcyLDg1MDAwMjc5MTcsNjMxNzQ2OTk0NjgsMTc1ODExMjYzNzA1LDIxODU1MDkzMTLaAigKEgn4aHHGMFtPQBGbI%2BdaJlMiQBISCQAAAAAAU3ZAEchK5VCzQmRA4AIB&sll=107.994659%2C22.734181&sspn=205.150347%2C124.610105&text=%D1%81%D1%82%D1%80%D0%BE%D0%B8%D1%82%D0%B5%D0%BB%D1%8C%D0%BD%D1%8B%D0%B5%20%D0%B3%D0%B8%D0%BF%D0%B5%D1%80%D0%BC%D0%B0%D1%80%D0%BA%D0%B5%D1%82%D1%8B&z=2.8"
    try:
        scrolling_and_parsing(
            driver=driver, 
            url=url,
            category=SEARCH_CATEGORY,
        )
    finally:
        driver.quit()
        logger.info("🔚 Браузер закрыт")


if __name__ == '__main__':
    main()
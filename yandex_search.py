from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
from captcha_solver import CaptchaSolver
import time
import logging
import json
import random
from urllib.parse import urlparse, unquote

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("parser_yandex.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

API_KEY="6c7965e3fd87d723b5152ec532e4aced"

# 🎯 Настройки поведения
MIN_DELAY = 2
MAX_DELAY = 8
SCROLL_PAUSE = 0.3
MAX_CAPTCHA_ATTEMPTS = 3

# 🚫 Домены для пропуска
DO_NOT_PARSE = ["yandex.ru", "2gis.ru", "market.yandex.ru"]

# ================= ЛОГИРОВАНИЕ =================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("parser_yandex.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ================= STEALTH-НАСТРОЙКИ БРАУЗЕРА =================
def create_stealth_driver():
    """Создаёт Firefox с настройками для скрытия автоматизации"""
    options = Options()
    options.add_argument("--window-size=1920,1080")
    
    # 🛡️ Скрытие признаков автоматизации
    options.set_preference("dom.webdriver.enabled", False)
    options.set_preference("useAutomationExtension", False)
    options.set_preference("privacy.resistFingerprinting", False)
    
    # 🎭 Рандомизация User-Agent
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:120.0) Gecko/20100101 Firefox/120.0",
    ]
    options.set_preference("general.useragent.override", random.choice(user_agents))
    
    service = Service(executable_path="geckodriver.exe")
    driver = webdriver.Firefox(service=service, options=options)
    
    # 🧬 Скрипт для скрытия navigator.webdriver
    driver.execute_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['ru-RU', 'ru', 'en-US', 'en'] });
    """)
    
    return driver


# ================= ИМИТАЦИЯ ПОВЕДЕНИЯ =================
def mimic_human_behavior(driver):
    """Имитирует действия реального пользователя"""
    try:
        # 📜 Случайный скролл
        if random.random() < 0.7:
            direction = random.choice([1, -1])
            distance = random.randint(200, 600) * direction
            driver.execute_script(f"window.scrollBy(0, {distance});")
            time.sleep(random.uniform(SCROLL_PAUSE * 0.5, SCROLL_PAUSE * 1.5))
        
        # 🖱️ Имитация движения мыши
        if random.random() < 0.3:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, "a, button, input")
                if elements:
                    target = random.choice(elements[:5])
                    actions = ActionChains(driver)
                    actions.move_to_element_with_offset(target, 
                                                       random.randint(-10, 10), 
                                                       random.randint(-10, 10))
                    actions.pause(random.uniform(0.3, 1.2)).perform()
            except:
                pass
        
        # ⏸️ Случайная пауза
        if random.random() < 0.4:
            time.sleep(random.uniform(1, 3))
            
        return True
    except Exception as e:
        logger.debug(f"⚠ Ошибка имитации поведения: {e}")
        return False


def scroll_to_bottom_smooth(driver):
    """Плавный скролл до конца страницы"""
    try:
        total_height = driver.execute_script("return document.body.scrollHeight")
        current_position = 0
        
        while current_position < total_height:
            scroll_step = random.randint(150, 400)
            driver.execute_script(f"window.scrollBy(0, {scroll_step});")
            current_position += scroll_step
            time.sleep(random.uniform(SCROLL_PAUSE * 0.3, SCROLL_PAUSE * 1.2))
            
            if random.random() < 0.15:
                time.sleep(random.uniform(0.5, 2))
                
            if random.random() < 0.1 and current_position > 300:
                driver.execute_script(f"window.scrollBy(0, -{random.randint(50, 150)});")
                time.sleep(random.uniform(0.3, 0.8))
        
        return True
    except Exception as e:
        logger.warning(f"⚠ Ошибка скролла: {e}")
        return False


# ================= ПРОВЕРКА НА КАПЧУ =================
def is_captcha_detected(driver):
    """Проверяет, появилась ли капча Яндекса"""
    captcha_indicators = [
        "checkbox-captcha",
        "smartcaptcha", 
        "CaptchaTitle",
        "Подтвердите, что запросы отправляли вы",
        "Я не робот",
    ]
    
    page_source = driver.page_source.lower()
    for indicator in captcha_indicators:
        if indicator.lower() in page_source:
            return True
    
    if "captcha" in driver.current_url.lower():
        return True
    
    return False


# ================= РЕШЕНИЕ КАПЧИ ЧЕРЕЗ captcha_solver =================
def solve_captcha_with_library(driver, max_attempts=MAX_CAPTCHA_ATTEMPTS):
    """
    Решает капчу Яндекса с помощью библиотеки captcha_solver.
    Возвращает True при успехе, False при неудаче.
    """
    if not API_KEY:
        logger.error("❌ CAPTCHA_SOLVER_API_KEY не настроен!")
        return False
    
    try:
        logger.info("🔄 Запуск решения капчи через captcha_solver...")
        
        solver = CaptchaSolver(
            page=driver.current_url,
            api_key=API_KEY,
            debug=True,
            attempts=max_attempts,
        )
        
        # solve_other() — универсальный метод для различных типов капч
        result = solver.solve_other()
        
        if result:
            logger.info("✅ Капча успешно решена!")
            time.sleep(random.uniform(2, 4))  # Пауза после решения
            return True
        else:
            logger.warning("⚠ Не удалось решить капчу")
            return False
            
    except Exception as e:
        logger.error(f"❌ Ошибка при решении капчи: {type(e).__name__}: {e}")
        return False


# ================= ПАРСИНГ ССЫЛОК =================
def parse_links(driver):
    """Парсит ссылки на текущей странице"""
    try:
        mimic_human_behavior(driver)
        time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
        
        # Закрытие попапов
        try:
            button_close = WebDriverWait(driver, 2).until(
                EC.element_to_be_clickable((By.CLASS_NAME, "DistributionButtonClose"))
            )
            driver.execute_script("arguments[0].click();", button_close)
            time.sleep(random.uniform(0.3, 1))
        except (NoSuchElementException, TimeoutException):
            pass
        
        selectors = [
            "a.Path-Item.link.action-counter",
            "a[data-counter='[\"b\"]']",
            "a.OrganicTitle-Link",
        ]
        
        parsed_count = 0
        seen_urls = set()
        
        for selector in selectors:
            try:
                a_blocks = WebDriverWait(driver, 3).until(
                    EC.presence_of_all_elements_located((By.CSS_SELECTOR, selector))
                )
                logger.info(f"✓ Найдено {len(a_blocks)} элементов: {selector[:40]}...")
                
                for a_block in a_blocks:
                    try:
                        target_url = None
                        
                        data_pavo7 = a_block.get_attribute("data-pavo7")
                        if data_pavo7:
                            try:
                                pavo_data = json.loads(data_pavo7.replace('&quot;', '"'))
                                target_url = pavo_data.get("noRedirectUrl")
                                if target_url:
                                    target_url = unquote(target_url)
                            except (json.JSONDecodeError, KeyError):
                                pass
                        
                        if not target_url:
                            href = a_block.get_attribute("href")
                            if href and href.startswith("http") and "yandex.ru/search/_crpd" not in href:
                                target_url = href
                        
                        if not target_url:
                            continue
                        
                        # Очистка от трекеров
                        parsed = urlparse(target_url)
                        if parsed.query:
                            from urllib.parse import parse_qs, urlencode
                            params = parse_qs(parsed.query)
                            clean_params = {k: v for k, v in params.items() 
                                          if not k.startswith(("utm_", "yclid", "calltouch", "_openstat", "baobab", "ctime"))}
                            query_str = "?" + urlencode(clean_params, doseq=True) if clean_params else ""
                        else:
                            query_str = ""
                        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}{query_str}".rstrip("?")
                        
                        if not clean_url or clean_url in seen_urls:
                            continue
                        
                        domain = urlparse(clean_url).netloc
                        if domain in DO_NOT_PARSE:
                            logger.debug(f"Пропущен: {domain}")
                            continue
                        
                        with open("parsed_links.txt", "a+", encoding="utf-8") as file:
                            file.write(f"{clean_url}\n")
                        
                        seen_urls.add(clean_url)
                        parsed_count += 1
                        logger.info(f"  → {clean_url}")
                        
                    except Exception as e:
                        logger.debug(f"Ошибка элемента: {e}")
                        continue
                
                if parsed_count > 0:
                    break
            except (NoSuchElementException, TimeoutException):
                continue
        
        if parsed_count == 0:
            logger.warning("⚠ Не найдено ссылок на странице")
            return False
            
        logger.info(f"✓ Страница: {parsed_count} новых ссылок")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка parse_links: {type(e).__name__}: {e}")
        return False


# ================= ПЕРЕХОД НА СЛЕДУЮЩУЮ СТРАНИЦУ =================
def click_next_page(driver):
    """Скроллит, имитирует поведение, кликает «дальше»"""
    try:
        logger.info("📜 Скроллим до конца страницы...")
        scroll_to_bottom_smooth(driver)
        time.sleep(random.uniform(1, 3))
        mimic_human_behavior(driver)
        
        next_btn = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "a.Pager-Item_type_next"))
        )
        
        driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", next_btn)
        time.sleep(random.uniform(0.5, 1.5))
        
        driver.execute_script("arguments[0].click();", next_btn)
        logger.info("✓ Клик по кнопке «дальше»")
        
        WebDriverWait(driver, 10).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        time.sleep(random.uniform(2, 5))
        
        return True
        
    except (NoSuchElementException, TimeoutException):
        logger.info("Кнопка «дальше» не найдена — последняя страница")
        return False
    except Exception as e:
        logger.warning(f"Ошибка при клике: {e}")
        return False


# ================= ГЛАВНАЯ ФУНКЦИЯ =================
def main():
    search_query = input("Request item: ").strip()
    if not search_query:
        logger.error("Запрос не может быть пустым")
        return
        
    clear_query = search_query if " " not in search_query else '+'.join(search_query.split())
    logger.info(f"[+] Запрос: {clear_query}")
    
    location = input("Location: ").strip()
    location_param = location if " " not in location else '+'.join(location.split())
    
    base_url = f"https://yandex.ru/search/?text={clear_query}+{location_param}&lr=213&clid=2353835"
    
    page = 1
    max_pages = 30
    
    # 🚀 Создаём браузер
    driver = create_stealth_driver()
    
    try:
        # ✅ ЗАГРУЗКА ПЕРВОЙ СТРАНИЦЫ (исправление!)
        logger.info(f"🌐 Открываем: {base_url}")
        driver.get(base_url)
        time.sleep(random.uniform(3, 7))  # Даём время на загрузку контента и выполнение JS
        
        # 🔍 Проверка на капчу сразу после загрузки
        if is_captcha_detected(driver):
            logger.warning("⚠ Капча обнаружена сразу после загрузки!")
            if not solve_captcha_with_library(driver):
                logger.error("❌ Не удалось решить начальную капчу")
                return
            time.sleep(random.uniform(2, 4))
        
        logger.info(f"✓ Страница загружена, начинаем парсинг")
        
        while page <= max_pages:
            logger.info(f"\n>>> Страница {page}")
            
            # 🔍 Повторная проверка на капчу (может появиться после действий)
            if is_captcha_detected(driver):
                logger.warning("⚠ Обнаружена капча!")
                if solve_captcha_with_library(driver):
                    logger.info("✅ Капча решена, продолжаем...")
                    time.sleep(random.uniform(2, 5))
                else:
                    logger.error("❌ Не удалось решить капчу")
                    break
            
            # 📋 Парсим ссылки на текущей странице
            if not parse_links(driver):
                logger.warning("⚠ Пропуск страницы")
                if not click_next_page(driver):
                    break
                page += 1
                continue
            
            # ➡️ Переход на следующую страницу
            if not click_next_page(driver):
                logger.info("✓ Достигнута последняя страница")
                break
                
            page += 1
            time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
            
    except KeyboardInterrupt:
        logger.info("\n⚠ Прервано пользователем")
    except WebDriverException as e:
        logger.error(f"❌ Ошибка драйвера: {e}")
    except Exception as e:
        logger.error(f"Критическая ошибка: {type(e).__name__}: {e}")
    finally:
        logger.info(f"\n✓ Завершено. Обработано страниц: {page-1}")
        driver.quit()

if __name__ == '__main__':
    main()
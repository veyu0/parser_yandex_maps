from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                             QTextEdit, QFileDialog, QProgressBar, QMessageBox,
                             QGroupBox, QFormLayout)
from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtGui import QFont
from datetime import datetime
import time
import logging
import os
import sys
import pandas as pd
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

# ==================== НАСТРОЙКА ЛОГИРОВАНИЯ ====================

def setup_global_logging():
    """Глобальная настройка логирования"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("parser_yandex_maps.log", encoding='utf-8'),
            logging.StreamHandler()
        ]
    )

setup_global_logging()
logger = logging.getLogger(__name__)

EXPORT_FILE = "yandex_maps_russia.xlsx"

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def get_driver_path():
    """Получает путь к драйверу (работает и в .exe)"""
    if getattr(sys, 'frozen', False):
        application_path = os.path.dirname(sys.executable)
    else:
        application_path = os.path.dirname(os.path.abspath(__file__))
    
    # Пробуем Firefox
    geckodriver_path = os.path.join(application_path, 'geckodriver.exe')
    if os.path.exists(geckodriver_path):
        logger.info(f"✅ Найден geckodriver: {geckodriver_path}")
        return geckodriver_path
    
    # Пробуем Chrome
    chromedriver_path = os.path.join(application_path, 'chromedriver.exe')
    if os.path.exists(chromedriver_path):
        logger.info(f"✅ Найден chromedriver: {chromedriver_path}")
        return chromedriver_path
    
    raise FileNotFoundError(
        "❌ Не найден драйвер!\nПоложите geckodriver.exe или chromedriver.exe в папку с программой."
    )

def init_excel_file(filepath, columns):
    """Создаёт Excel-файл с заголовками, если он не существует"""
    if not os.path.exists(filepath):
        df = pd.DataFrame(columns=columns)
        df.to_excel(filepath, index=False, engine='openpyxl')
        logger.info(f"📄 Создан файл: {filepath}")

def append_to_excel(filepath, data_dict):
    """Добавляет одну строку в Excel-файл"""
    try:
        if os.path.exists(filepath):
            df_existing = pd.read_excel(filepath, engine='openpyxl')
            df_new = pd.DataFrame([data_dict])
            df_combined = pd.concat([df_existing, df_new], ignore_index=True)
        else:
            df_combined = pd.DataFrame([data_dict])
        
        df_combined.to_excel(filepath, index=False, engine='openpyxl')
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения в Excel: {e}")
        return False

def _scroll_list_container(driver, scroll_amount=600):
    """Универсальная прокрутка контейнера"""
    try:
        result = driver.execute_script(f"""
        var list = document.querySelector('ul.search-list-view__list');
        if (!list) return {{found: false, reason: 'list not found'}};
        
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
        
        window.scrollBy(0, {scroll_amount});
        return {{found: false, reason: 'fallback to window'}};
        """)
        
        if result.get('found'):
            return result.get('scrolled', False)
        return True
    except Exception as e:
        logger.warning(f"⚠️ Ошибка при скролле: {e}")
        driver.execute_script(f"window.scrollBy(0, {scroll_amount});")
        return True

# ==================== РАБОЧИЙ ПОТОК ПАРСИНГА ====================

class ParserWorker(QThread):
    """Фоновый поток для парсинга"""
    log_signal = pyqtSignal(str, str)
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(int)
    error_signal = pyqtSignal(str)
    
    def __init__(self, url, category, filepath):
        super().__init__()
        self.url = url
        self.category = category
        self.filepath = filepath
        self.driver = None
        self.is_stopped = False
        self.browser_type = None
    
    def custom_log(self, message, level="INFO"):
        """Отправка логов в GUI"""
        self.log_signal.emit(message, level)
    
    def parsing(self, item, driver):
        """Парсинг одной карточки"""
        try:
            item.click()
            self.custom_log("Item clicked", "INFO")
            
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "a.card-title-view__title-link"))
            )
            time.sleep(1)
            
            title = phone = site = address = None
            
            try:
                title = WebDriverWait(driver, 3).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "a.card-title-view__title-link"))
                ).text.strip()
            except:
                self.custom_log('⚠️ Title not found', "WARNING")
            
            try:
                phone = WebDriverWait(driver, 3).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "span[itemprop='telephone']"))
                ).text.strip()
            except:
                self.custom_log('⚠️ Phone not found', "WARNING")
            
            try:
                site = WebDriverWait(driver, 3).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "span.business-urls-view__text"))
                ).text.strip()
            except:
                self.custom_log('⚠️ Site not found', "WARNING")
            
            try:
                address = WebDriverWait(driver, 3).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.business-contacts-view__address-link"))
                ).text.strip()
            except:
                self.custom_log('⚠️ Address not found', "WARNING")
            
            driver.back()
            self.custom_log("Back to previous page", "INFO")
            
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CLASS_NAME, "search-list-view__list"))
            )
            time.sleep(1)
            
            return title, phone, site, address
            
        except Exception as e:
            self.custom_log(f"✗ Ошибка парсинга: {e}", "ERROR")
            return None, None, None, None
    
    def run(self):
        """Основной метод потока"""
        try:
            # Получаем путь к драйверу
            driver_path = get_driver_path()
            
            # Определяем тип браузера по имени файла
            if 'chrome' in driver_path.lower():
                from selenium.webdriver.chrome.options import Options as ChromeOptions
                from selenium.webdriver.chrome.service import Service as ChromeService
                
                self.custom_log("🚀 Инициализация Chrome...", "INFO")
                options = ChromeOptions()
                options.add_argument("--headless")
                options.add_argument("--disable-gpu")
                options.add_argument("--no-sandbox")
                service = ChromeService(driver_path)
                self.driver = webdriver.Chrome(service=service, options=options)
                self.browser_type = 'chrome'
            else:
                self.custom_log("🚀 Инициализация Firefox...", "INFO")
                options = Options()
                options.add_argument("--headless")
                service = Service(driver_path)
                self.driver = webdriver.Firefox(service=service, options=options)
                self.browser_type = 'firefox'
            
            self.custom_log("✅ Браузер запущен", "INFO")
            
            # Переход на URL
            self.driver.get(self.url)
            wait = WebDriverWait(self.driver, 10)
            
            # Инициализация Excel
            excel_columns = ['timestamp', 'category', 'city', 'title', 'phone', 'site']
            init_excel_file(self.filepath, excel_columns)
            
            processed_urls = set()
            total_processed = 0
            empty_scrolls = 0
            MAX_EMPTY_SCROLLS = 3
            BATCH_SIZE = 5
            
            self.custom_log(f"🔄 Начинаем прокрутку порциями по {BATCH_SIZE}...", "INFO")
            
            while not self.is_stopped:
                # Поиск элементов
                try:
                    list_container = wait.until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "ul.search-list-view__list"))
                    )
                    items = list_container.find_elements(By.TAG_NAME, "li")
                    visible_items = [i for i in items if i.is_displayed() and i.text.strip()]
                except Exception as e:
                    self.custom_log(f"⚠️ Не удалось получить элементы: {e}", "WARNING")
                    visible_items = []
                    time.sleep(1)
                    continue
                
                # Сбор кандидатов
                candidates = []
                for idx, item in enumerate(visible_items):
                    try:
                        link = item.find_element(By.CSS_SELECTOR, "a[href*='/maps/org/']")
                        item_url = link.get_attribute("href")
                        if item_url and item_url not in processed_urls:
                            candidates.append((idx, item_url))
                    except:
                        continue
                
                # Если нет новых элементов
                if not candidates:
                    empty_scrolls += 1
                    self.custom_log(f"⏳ Нет новых элементов ({empty_scrolls}/{MAX_EMPTY_SCROLLS})...", "INFO")
                    
                    if empty_scrolls >= MAX_EMPTY_SCROLLS:
                        self.custom_log("✅ Прокрутка завершена", "INFO")
                        break
                    
                    _scroll_list_container(self.driver)
                    time.sleep(2.5)
                    continue
                
                empty_scrolls = 0
                batch = candidates[:BATCH_SIZE]
                self.custom_log(f"📦 Новая порция: {len(batch)} элементов (всего: {total_processed})", "INFO")
                
                # Обработка батча
                for batch_idx, (item_index, item_url) in enumerate(batch, 1):
                    if self.is_stopped:
                        break
                    
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
                        
                        title, phone, site, address = self.parsing(fresh_item, self.driver)
                        
                        if title is None:
                            continue
                        
                        self.custom_log(f"→ #{total_processed + batch_idx}: '{title[:40]}' | {phone} | {site}", "INFO")
                        
                        record = {
                            'timestamp': datetime.utcnow(),
                            'category': self.category,
                            'city': address,
                            'title': title,
                            'phone': phone,
                            'site': site
                        }
                        
                        if append_to_excel(self.filepath, record):
                            self.custom_log(f"✅ Сохранено", "INFO")
                        
                    except Exception as e:
                        self.custom_log(f"✗ Ошибка в элементе: {e}", "ERROR")
                        try:
                            if self.driver.current_url != self.url:
                                self.driver.back()
                                wait.until(EC.presence_of_element_located(
                                    (By.CSS_SELECTOR, "ul.search-list-view__list")
                                ))
                                time.sleep(1)
                        except:
                            pass
                        continue
                
                if self.is_stopped:
                    break
                
                total_processed += len(batch)
                self.progress_signal.emit(total_processed)
                self.custom_log(f"✓ Батч завершён. Всего: {total_processed}", "INFO")
                
                _scroll_list_container(self.driver)
                time.sleep(2.5)
            
            self.custom_log(f"🎉 Готово! Обработано: {total_processed}", "INFO")
            self.finished_signal.emit(total_processed)
            
        except FileNotFoundError as e:
            self.error_signal.emit(str(e))
        except Exception as e:
            self.error_signal.emit(f"Критическая ошибка: {e}")
            self.custom_log(f"❌ {e}", "ERROR")
        
        finally:
            if self.driver:
                try:
                    self.driver.quit()
                    self.custom_log("🔒 Браузер закрыт", "INFO")
                except:
                    pass
    
    def stop(self):
        """Остановка парсинга"""
        self.is_stopped = True
        self.custom_log("🛑 Остановка по запросу пользователя...", "WARNING")


# ==================== ГЛАВНОЕ ОКНО ====================

class ParserWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.parser_thread = None
        self.init_ui()
    
    def init_ui(self):
        """Инициализация интерфейса"""
        self.setWindowTitle("Yandex Maps Parser - PyQt6")
        self.setGeometry(100, 100, 900, 700)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # Группа настроек
        settings_group = QGroupBox("📋 Настройки парсинга")
        settings_layout = QFormLayout()
        settings_layout.setSpacing(8)
        
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://yandex.ru/maps/...")
        self.url_input.setMinimumHeight(30)
        settings_layout.addRow("URL Яндекс Карт:", self.url_input)
        
        self.category_input = QLineEdit()
        self.category_input.setText("Рестораны")
        self.category_input.setMinimumHeight(30)
        settings_layout.addRow("Категория:", self.category_input)
        
        file_layout = QHBoxLayout()
        self.file_input = QLineEdit()
        self.file_input.setText("yandex_maps_russia.xlsx")
        self.file_input.setMinimumHeight(30)
        file_layout.addWidget(self.file_input)
        
        browse_btn = QPushButton("📁 Обзор...")
        browse_btn.clicked.connect(self.browse_file)
        file_layout.addWidget(browse_btn)
        settings_layout.addRow("Файл Excel:", file_layout)
        
        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)
        
        # Кнопки управления
        btn_layout = QHBoxLayout()
        
        self.start_btn = QPushButton("▶ Запустить парсинг")
        self.start_btn.setMinimumHeight(40)
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                border-radius: 5px;
                padding: 5px 15px;
            }
            QPushButton:hover { background-color: #45a049; }
            QPushButton:disabled { background-color: #cccccc; }
        """)
        self.start_btn.clicked.connect(self.start_parsing)
        btn_layout.addWidget(self.start_btn)
        
        self.stop_btn = QPushButton("⏹ Остановить")
        self.stop_btn.setMinimumHeight(40)
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                font-weight: bold;
                border-radius: 5px;
                padding: 5px 15px;
            }
            QPushButton:hover { background-color: #da190b; }
            QPushButton:disabled { background-color: #cccccc; }
        """)
        self.stop_btn.clicked.connect(self.stop_parsing)
        self.stop_btn.setEnabled(False)
        btn_layout.addWidget(self.stop_btn)
        
        layout.addLayout(btn_layout)
        
        # Прогресс бар
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimumHeight(25)
        self.progress_bar.setFormat("Обработано: %v")
        layout.addWidget(self.progress_bar)
        
        # Лог
        log_group = QGroupBox("📝 Лог парсинга")
        log_layout = QVBoxLayout()
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #3e3e3e;
                border-radius: 3px;
                padding: 5px;
            }
        """)
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group, 1)
        
        self.statusBar().showMessage("Готов к работе", 0)
    
    def browse_file(self):
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Сохранить как", "yandex_maps_russia.xlsx",
            "Excel Files (*.xlsx);;All Files (*)"
        )
        if filepath:
            self.file_input.setText(filepath)
    
    def append_log(self, message, level="INFO"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        color = {"ERROR": "#ff6b6b", "WARNING": "#ffd93d"}.get(level, "#6bcb77")
        
        self.log_text.append(
            f'<span style="color: #888;">[{timestamp}]</span> '
            f'<span style="color: {color};">{message}</span>'
        )
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )
    
    def start_parsing(self):
        url = self.url_input.text().strip()
        category = self.category_input.text().strip()
        filepath = self.file_input.text().strip()
        
        if not url or not category or not filepath:
            QMessageBox.warning(self, "Ошибка", "Заполните все поля!")
            return
        
        if not url.startswith("http"):
            QMessageBox.warning(self, "Ошибка", "Некорректный URL!")
            return
        
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.url_input.setEnabled(False)
        self.category_input.setEnabled(False)
        self.file_input.setEnabled(False)
        
        self.log_text.clear()
        self.progress_bar.setValue(0)
        self.statusBar().showMessage("Парсинг запущен...", 0)
        
        self.parser_thread = ParserWorker(url, category, filepath)
        self.parser_thread.log_signal.connect(self.append_log)
        self.parser_thread.progress_signal.connect(self.progress_bar.setValue)
        self.parser_thread.finished_signal.connect(self.parsing_finished)
        self.parser_thread.error_signal.connect(self.parsing_error)
        
        self.parser_thread.start()
        self.append_log("🚀 Парсинг запущен", "INFO")
    
    def stop_parsing(self):
        if self.parser_thread and self.parser_thread.isRunning():
            self.append_log("🛑 Остановка...", "WARNING")
            self.parser_thread.stop()
            self.stop_btn.setEnabled(False)
    
    def parsing_finished(self, count):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.url_input.setEnabled(True)
        self.category_input.setEnabled(True)
        self.file_input.setEnabled(True)
        
        self.statusBar().showMessage(f"Завершено! Обработано: {count}", 5000)
        QMessageBox.information(self, "Готово", f"Парсинг завершён!\nОбработано записей: {count}")
    
    def parsing_error(self, error_msg):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.url_input.setEnabled(True)
        self.category_input.setEnabled(True)
        self.file_input.setEnabled(True)
        
        self.statusBar().showMessage("Ошибка!", 5000)
        QMessageBox.critical(self, "Ошибка", error_msg)


# ==================== ЗАПУСК ====================

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    window = ParserWindow()
    window.show()
    
    sys.exit(app.exec())
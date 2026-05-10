import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import queue
import logging
import os
import time
from datetime import datetime
import pandas as pd
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from webdriver_manager.firefox import GeckoDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

# ==================== НАСТРОЙКИ ====================
DEFAULT_EXPORT_NAME = "yandex_maps_data.xlsx"
BATCH_SIZE = 5
MAX_EMPTY_SCROLLS = 3

# ==================== ЛОГИКА ПАРСЕРА ====================
class QueueHandler(logging.Handler):
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue
    def emit(self, record):
        self.log_queue.put(self.format(record))

def _scroll_list_container(driver, scroll_amount=600):
    try:
        result = driver.execute_script(f"""
        var list = document.querySelector('ul.search-list-view__list');
        if (!list) return {{found: false, reason: 'list not found'}};
        var el = list;
        while (el && el !== document.documentElement) {{
            if (el.scrollHeight > el.clientHeight && 
               (getComputedStyle(el).overflowY === 'auto' || getComputedStyle(el).overflowY === 'scroll')) {{
                var oldTop = el.scrollTop;
                el.scrollTop += {scroll_amount};
                return {{found: true, scrolled: el.scrollTop > oldTop}};
            }}
            el = el.parentElement;
        }}
        window.scrollBy(0, {scroll_amount});
        return {{found: false, reason: 'window'}};
        """)
        if result.get('found'): return result.get('scrolled', True)
        return True
    except:
        driver.execute_script(f"window.scrollBy(0, {scroll_amount});")
        return True

def init_excel_file(filepath, columns):
    if not os.path.exists(filepath):
        pd.DataFrame(columns=columns).to_excel(filepath, index=False, engine='openpyxl')

def append_to_excel(filepath, data_dict):
    try:
        if os.path.exists(filepath):
            df_existing = pd.read_excel(filepath, engine='openpyxl')
            df_new = pd.DataFrame([data_dict]).reindex(columns=df_existing.columns)
            df_combined = pd.concat([df_existing, df_new], ignore_index=True)
        else:
            df_combined = pd.DataFrame([data_dict])
        df_combined.to_excel(filepath, index=False, engine='openpyxl')
        return True
    except Exception as e:
        logging.error(f"❌ Ошибка сохранения в Excel: {e}")
        return False

def parsing(item, driver, wait, selected_fields):
    item.click()
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "a.card-title-view__title-link")))
    time.sleep(0.8)

    def safe_find(css, timeout=3):
        try:
            return wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, css)), timeout).text.strip()
        except:
            return None

    result = {}
    if selected_fields.get('title'):
        result['title'] = safe_find("a.card-title-view__title-link")
    if selected_fields.get('phone'):
        result['phone'] = safe_find("span[itemprop='telephone']")
    if selected_fields.get('site'):
        result['site'] = safe_find("span.business-urls-view__text")
    if selected_fields.get('address'):
        result['address'] = safe_find("div.business-contacts-view__address-link")

    driver.back()
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "ul.search-list-view__list")))
    time.sleep(0.5)
    return result

def run_scraping(url, category, selected_fields, save_dir, log_queue, stop_event):
    logger = logging.getLogger("scraper")
    logger.handlers.clear()
    logger.addHandler(QueueHandler(log_queue))
    logger.setLevel(logging.INFO)

    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    
    service = Service(executable_path="geckodriver.exe")
    driver = webdriver.Firefox(service=service, options=options)
    wait = WebDriverWait(driver, 10)

    try:
        driver.get(url)
        
        # Динамические колонки
        dynamic_cols = [k for k, v in selected_fields.items() if v]
        all_cols = ['timestamp', 'category'] + dynamic_cols
        export_path = os.path.join(save_dir, DEFAULT_EXPORT_NAME)
        
        init_excel_file(export_path, all_cols)
        processed_urls = set()
        total_processed = 0
        empty_scrolls = 0

        logger.info(f"🔄 Начинаем прокрутку... Колонки: {', '.join(all_cols)}")

        while not stop_event.is_set():
            try:
                list_container = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "ul.search-list-view__list")))
                items = list_container.find_elements(By.TAG_NAME, "li")
                visible_items = [i for i in items if i.is_displayed() and i.text.strip()]
            except:
                visible_items = []

            candidates = []
            for idx, item in enumerate(visible_items):
                try:
                    link = item.find_element(By.CSS_SELECTOR, "a[href*='/maps/org/']")
                    item_url = link.get_attribute("href")
                    if item_url and item_url not in processed_urls:
                        candidates.append((idx, item_url))
                except:
                    continue

            if not candidates:
                empty_scrolls += 1
                logger.info(f"⏳ Нет новых элементов ({empty_scrolls}/{MAX_EMPTY_SCROLLS})...")
                if empty_scrolls >= MAX_EMPTY_SCROLLS:
                    logger.info("✅ Прокрутка завершена.")
                    break
                _scroll_list_container(driver)
                time.sleep(2.5)
                continue

            empty_scrolls = 0
            batch = candidates[:BATCH_SIZE]
            logger.info(f"📦 Новая порция: {len(batch)} элементов (всего: {total_processed})")

            for _, (item_index, item_url) in enumerate(batch, 1):
                if stop_event.is_set(): break
                try:
                    list_container = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "ul.search-list-view__list")))
                    items = list_container.find_elements(By.TAG_NAME, "li")
                    visible_items = [i for i in items if i.is_displayed() and i.text.strip()]
                    if item_index >= len(visible_items): continue
                    
                    fresh_item = visible_items[item_index]
                    processed_urls.add(item_url)
                    data = parsing(fresh_item, driver, wait, selected_fields)

                    logger.info(f"→ {data.get('title', '')[:40]} | {data.get('phone', '')} | {data.get('site', '')}")
                    
                    record = {
                        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        'category': category
                    }
                    # Добавляем только выбранные поля
                    for field in dynamic_cols:
                        record[field] = data.get(field, '')
                        
                    if append_to_excel(export_path, record):
                        logger.info("✅ Сохранено")
                    else:
                        logger.warning("⚠️ Не удалось сохранить")
                except Exception as e:
                    logger.error(f"✗ Ошибка элемента: {e}")
                    try:
                        if driver.current_url != url:
                            driver.back()
                            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "ul.search-list-view__list")))
                    except: pass
                    continue

            total_processed += len(batch)
            logger.info(f"✓ Батч завершён. Всего: {total_processed}")
            if not stop_event.is_set():
                _scroll_list_container(driver)
                time.sleep(2.5)

        logger.info(f"🎉 Готово! Обработано: {total_processed} | Файл: {export_path}")
    except Exception as e:
        logger.error(f"🔴 Критическая ошибка: {e}")
    finally:
        driver.quit()
        log_queue.put(None)

# ==================== GUI ====================
class ParserApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Yandex Maps Parser v2.0")
        self.root.geometry("750x520")
        self.stop_event = threading.Event()
        self.log_queue = queue.Queue()
        self.worker = None
        self.save_dir = tk.StringVar(value=os.path.expanduser("~"))

        self._build_ui()
        self._start_log_updater()

    def _build_ui(self):
        frame_input = ttk.LabelFrame(self.root, text="Настройки")
        frame_input.pack(fill=tk.X, padx=10, pady=5)

        # URL
        ttk.Label(frame_input, text="URL поиска:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.entry_url = ttk.Entry(frame_input, width=70)
        self.entry_url.insert(0, "https://yandex.ru/maps/?text=кафе")
        self.entry_url.grid(row=0, column=1, padx=5, pady=5)

        # Категория
        ttk.Label(frame_input, text="Категория:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.entry_category = ttk.Entry(frame_input, width=70)
        self.entry_category.insert(0, "Кафе")
        self.entry_category.grid(row=1, column=1, padx=5, pady=5)

        # Папка сохранения
        ttk.Label(frame_input, text="Папка:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=5)
        frame_dir = ttk.Frame(frame_input)
        frame_dir.grid(row=2, column=1, sticky=tk.W, padx=5, pady=5)
        self.lbl_dir = ttk.Label(frame_dir, textvariable=self.save_dir, width=50, anchor="w")
        self.lbl_dir.pack(side=tk.LEFT, padx=5)
        ttk.Button(frame_dir, text="📁 Выбрать", command=self._select_dir).pack(side=tk.LEFT, padx=5)

        # Чекбоксы полей
        frame_fields = ttk.LabelFrame(self.root, text="Поля для парсинга")
        frame_fields.pack(fill=tk.X, padx=10, pady=5)
        self.fields = {
            'title': tk.BooleanVar(value=True),
            'phone': tk.BooleanVar(value=True),
            'site': tk.BooleanVar(value=True),
            'address': tk.BooleanVar(value=True)
        }
        field_labels = {'title': 'Название', 'phone': 'Телефон', 'site': 'Сайт', 'address': 'Город/Адрес'}
        for i, (key, label) in enumerate(field_labels.items()):
            ttk.Checkbutton(frame_fields, text=label, variable=self.fields[key]).grid(row=0, column=i, padx=10, pady=5)

        # Кнопки
        frame_btn = ttk.Frame(self.root)
        frame_btn.pack(fill=tk.X, padx=10, pady=5)
        self.btn_start = ttk.Button(frame_btn, text="▶ Запустить", command=self._start)
        self.btn_start.pack(side=tk.LEFT, padx=5)
        self.btn_stop = ttk.Button(frame_btn, text="⏹ Остановить", command=self._stop, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=5)

        # Лог
        ttk.Label(self.root, text="Лог выполнения:").pack(anchor=tk.W, padx=10, pady=(5,0))
        self.txt_log = scrolledtext.ScrolledText(self.root, height=16, state=tk.DISABLED, font=("Consolas", 9))
        self.txt_log.pack(fill=tk.BOTH, padx=10, pady=5)

    def _select_dir(self):
        dir_path = filedialog.askdirectory(initialdir=self.save_dir.get())
        if dir_path:
            self.save_dir.set(dir_path)

    def _start_log_updater(self):
        def check_queue():
            try:
                while True:
                    msg = self.log_queue.get_nowait()
                    if msg is None:
                        self._on_finished()
                        return
                    self.txt_log.config(state=tk.NORMAL)
                    self.txt_log.insert(tk.END, msg + "\n")
                    self.txt_log.see(tk.END)
                    self.txt_log.config(state=tk.DISABLED)
            except queue.Empty:
                pass
            self.root.after(100, check_queue)
        self.root.after(100, check_queue)

    def _start(self):
        url = self.entry_url.get().strip()
        category = self.entry_category.get().strip()
        if not url or not category:
            messagebox.showerror("Ошибка", "Заполните URL и Категорию")
            return
        if not any(v.get() for v in self.fields.values()):
            messagebox.showwarning("Внимание", "Выберите хотя бы одно поле для парсинга")
            return

        selected = {k: v.get() for k, v in self.fields.items()}
        self.stop_event.clear()
        self.btn_start.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.NORMAL)
        self.worker = threading.Thread(target=run_scraping, args=(
            url, category, selected, self.save_dir.get(), self.log_queue, self.stop_event
        ), daemon=True)
        self.worker.start()

    def _stop(self):
        self.stop_event.set()
        self.btn_stop.config(state=tk.DISABLED)

    def _on_finished(self):
        self.btn_start.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.DISABLED)
        messagebox.showinfo("Готово", "Парсинг завершён.\nФайл сохранён в выбранную папку.")

    def on_closing(self):
        self.stop_event.set()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = ParserApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
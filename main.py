import time
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver import ActionChains
from selenium.webdriver.common.by import By

headers = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/106.0.0.0 Safari/537.36",
    "accept-encoding": "gzip, deflate, br",
    "accept-language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
}


def get_data_html(url):
    options = webdriver.ChromeOptions()
    options.binary_location = "/Applications/Google Chrome Dev.app/Contents/MacOS/Google Chrome Dev"
    chrome_driver_binary = "[path to driver]"
    driver = webdriver.Chrome(chrome_driver_binary, chrome_options=options)
    driver.maximize_window()

    try:
        driver.get(url=url)
        time.sleep(5)
        while True:
            end_block = driver.find_element(By.CLASS_NAME, 'search-list-meta-view')
            if driver.find_elements(By.CLASS_NAME, 'add-business-view'):
                with open('index.html', 'w') as file:
                    file.write(driver.page_source)
                break
            else:
                action = ActionChains(driver)
                action.move_to_element(end_block).perform()
                time.sleep(5)
    except Exception as ex:
        print(ex)
    finally:
        driver.close()
        driver.quit()


def get_items_urls(file_path):
    with open(file_path) as file:
        src = file.read()

    soup = BeautifulSoup(src, 'lxml')
    items = soup.find_all(class_='search-snippet-view')

    urls = []
    for item in items:
        item_url = item.find('a', class_='search-snippet-view__link-overlay _focusable').get('href')
        urls.append('https://yandex.ru' + item_url)

    with open('urls.txt', 'w') as file:
        for url in urls:
            file.write(f'{url}\n')

    return '[INFO Urls collected!]'


def main():
    get_data_html(url='https://yandex.ru/maps/213/moscow/search/%D0%BE%D1%81%D0%B0%D0%B3%D0%BE%20%D0%BC%D0%BE%D1%81%D0%BA%D0%B2%D0%B0/?ll=37.650216%2C55.724799&page=28&sll=37.576943%2C55.724799&sspn=1.966553%2C0.847911&z=10')
    get_items_urls(file_path='[file_path]')


if __name__ == '__main__':
    main()
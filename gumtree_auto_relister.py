from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
import time
import schedule
import logging
import os
import json
import sys
import random
import traceback
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime

# Настройка логирования
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / f"gumtree_auto_relister_{datetime.now().strftime('%Y%m%d')}.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("GumtreeAutoRelister")

# Загрузка переменных окружения из файла .env
load_dotenv()

# Конфигурация
GUMTREE_EMAIL = os.getenv("GUMTREE_EMAIL")
GUMTREE_PASSWORD = os.getenv("GUMTREE_PASSWORD")
RELIST_INTERVAL_HOURS = int(os.getenv("RELIST_INTERVAL_HOURS", "24"))
HEADLESS = os.getenv("HEADLESS", "True").lower() == "true"
AD_DATA_FILE = os.getenv("AD_DATA_FILE", "ad_data.json")
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
RANDOM_DELAY_MIN = int(os.getenv("RANDOM_DELAY_MIN", "0"))  # минимальная задержка в минутах
RANDOM_DELAY_MAX = int(os.getenv("RANDOM_DELAY_MAX", "30"))  # максимальная задержка в минутах

class WebDriverWrapper:
    """Обертка для WebDriver с дополнительными функциями и обработкой исключений"""
    
    def __init__(self):
        self.driver = None
    
    def initialize(self):
        """Инициализация веб-драйвера"""
        options = webdriver.ChromeOptions()
        
        if HEADLESS:
            options.add_argument("--headless=new")  # Новый формат для последних версий Chrome
        
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-popup-blocking")
        
        # Использование user-agent для имитации реального пользователя
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.2 Safari/605.1.15"
        ]
        options.add_argument(f"user-agent={random.choice(user_agents)}")
        
        # Добавление аргумента для предотвращения обнаружения автоматизации
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        
        self.driver = webdriver.Chrome(options=options)
        self.driver.implicitly_wait(10)
        
        return self.driver
    
    def safe_find_element(self, by, value, timeout=10, clickable=False):
        """Безопасный поиск элемента с ожиданием"""
        try:
            if clickable:
                element = WebDriverWait(self.driver, timeout).until(
                    EC.element_to_be_clickable((by, value))
                )
            else:
                element = WebDriverWait(self.driver, timeout).until(
                    EC.presence_of_element_located((by, value))
                )
            return element
        except (TimeoutException, NoSuchElementException) as e:
            logger.warning(f"Элемент не найден: {by}={value}. Ошибка: {e}")
            return None
    
    def safe_find_elements(self, by, value, timeout=10):
        """Безопасный поиск элементов с ожиданием"""
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((by, value))
            )
            return self.driver.find_elements(by, value)
        except (TimeoutException, NoSuchElementException) as e:
            logger.warning(f"Элементы не найдены: {by}={value}. Ошибка: {e}")
            return []
    
    def safe_click(self, element, retry=3):
        """Безопасный клик по элементу с повторными попытками"""
        for attempt in range(retry):
            try:
                if element:
                    element.click()
                    return True
            except (StaleElementReferenceException, TimeoutException) as e:
                if attempt < retry - 1:
                    logger.warning(f"Ошибка при клике, повторная попытка {attempt+1}: {e}")
                    time.sleep(1)
                else:
                    logger.error(f"Не удалось выполнить клик после {retry} попыток: {e}")
                    return False
        return False
    
    def close(self):
        """Закрытие драйвера"""
        if self.driver:
            self.driver.quit()
            self.driver = None

class GumtreeAutoRelister:
    """Основной класс для автоматической переподачи объявлений на Gumtree"""
    
    def __init__(self):
        self.driver_wrapper = WebDriverWrapper()
        self.ad_data = None
    
    def login_to_gumtree(self):
        """Вход в аккаунт Gumtree"""
        driver = self.driver_wrapper.driver
        try:
            logger.info("Открытие страницы логина...")
            driver.get("https://www.gumtree.com/signin")
            
            # Ожидание загрузки страницы и принятие cookies если необходимо
            cookie_button = self.driver_wrapper.safe_find_element(By.ID, "onetrust-accept-btn-handler", timeout=5, clickable=True)
            if cookie_button:
                self.driver_wrapper.safe_click(cookie_button)
                logger.info("Cookies приняты")
            
            # Проверка наличия формы входа
            email_field = self.driver_wrapper.safe_find_element(By.ID, "email", timeout=10)
            if not email_field:
                logger.error("Форма входа не найдена")
                return False
            
            # Ввод email
            logger.info("Ввод email...")
            email_field.clear()
            email_field.send_keys(GUMTREE_EMAIL)
            
            # Ввод пароля
            logger.info("Ввод пароля...")
            password_field = self.driver_wrapper.safe_find_element(By.ID, "password")
            if password_field:
                password_field.clear()
                password_field.send_keys(GUMTREE_PASSWORD)
            else:
                logger.error("Поле пароля не найдено")
                return False
            
            # Нажатие кнопки логина
            logger.info("Нажатие кнопки входа...")
            login_button = self.driver_wrapper.safe_find_element(
                By.XPATH, "//button[contains(text(), 'Sign in')]", clickable=True
            )
            if not login_button:
                logger.error("Кнопка входа не найдена")
                return False
                
            self.driver_wrapper.safe_click(login_button)
            
            # Ожидание успешного входа
            account_link = self.driver_wrapper.safe_find_element(
                By.XPATH, "//a[contains(@href, '/my/ads')]", timeout=15
            )
            
            if account_link:
                logger.info("Вход выполнен успешно")
                return True
            else:
                # Дополнительная проверка на наличие ошибки входа
                error_element = self.driver_wrapper.safe_find_element(
                    By.XPATH, "//div[contains(@class, 'error') or contains(@class, 'alert')]", timeout=3
                )
                if error_element:
                    logger.error(f"Ошибка входа: {error_element.text}")
                else:
                    logger.error("Не удалось подтвердить успешный вход")
                return False
            
        except Exception as e:
            logger.error(f"Ошибка при попытке входа: {e}")
            logger.debug(traceback.format_exc())
            return False
    
    def delete_ad(self):
        """Удаление существующего объявления"""
        driver = self.driver_wrapper.driver
        try:
            logger.info("Переход на страницу моих объявлений...")
            driver.get("https://www.gumtree.com/my/ads")
            
            # Ожидание загрузки страницы с объявлениями
            ads_container = self.driver_wrapper.safe_find_element(By.CLASS_NAME, "my-items-list", timeout=10)
            if not ads_container:
                logger.warning("Контейнер с объявлениями не найден. Возможно, объявлений нет или структура страницы изменилась.")
                return True  # Считаем успешным, если контейнер не найден, т.к. нет объявлений для удаления
            
            # Проверка наличия объявлений
            ad_elements = self.driver_wrapper.safe_find_elements(
                By.XPATH, "//div[contains(@class, 'my-items-list')]/div[contains(@class, 'item')]"
            )
            
            if not ad_elements:
                logger.warning("Объявления не найдены. Нечего удалять.")
                return True  # Возвращаем True, так как нет объявлений для удаления
            
            logger.info(f"Найдено {len(ad_elements)} объявлений")
            
            # Попытка найти кнопку удаления разными способами
            # 1. Прямой поиск кнопки Delete/Remove
            delete_button = self.driver_wrapper.safe_find_element(
                By.XPATH, 
                "//div[contains(@class, 'my-items-list')]/div[contains(@class, 'item')][1]//button[contains(text(), 'Delete') or contains(text(), 'Remove')]",
                timeout=5
            )
            
            # 2. Если кнопка не найдена напрямую, ищем контекстное меню
            if not delete_button:
                logger.info("Прямая кнопка удаления не найдена, ищем через меню...")
                menu_button = self.driver_wrapper.safe_find_element(
                    By.XPATH, 
                    "//div[contains(@class, 'my-items-list')]/div[contains(@class, 'item')][1]//button[contains(@class, 'menu') or contains(@class, 'dropdown') or contains(@aria-label, 'menu')]",
                    timeout=5,
                    clickable=True
                )
                
                if menu_button:
                    self.driver_wrapper.safe_click(menu_button)
                    time.sleep(1)
                    
                    # Поиск кнопки Delete/Remove в открытом меню
                    delete_button = self.driver_wrapper.safe_find_element(
                        By.XPATH, 
                        "//button[contains(text(), 'Delete') or contains(text(), 'Remove')]",
                        timeout=5,
                        clickable=True
                    )
            
            # 3. Если всё еще не нашли, попробуем поискать по иконкам
            if not delete_button:
                logger.info("Ищем кнопку удаления по иконкам...")
                delete_button = self.driver_wrapper.safe_find_element(
                    By.XPATH, 
                    "//div[contains(@class, 'my-items-list')]/div[contains(@class, 'item')][1]//button[contains(@aria-label, 'delete') or contains(@aria-label, 'remove')]",
                    timeout=5,
                    clickable=True
                )
            
            if not delete_button:
                logger.error("Не удалось найти кнопку удаления объявления после всех попыток")
                # Добавляем скриншот для диагностики
                screenshot_path = f"logs/error_delete_button_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                driver.save_screenshot(screenshot_path)
                logger.info(f"Сохранен скриншот: {screenshot_path}")
                return False
            
            # Нажимаем на кнопку Delete
            logger.info("Нажатие на кнопку удаления...")
            if not self.driver_wrapper.safe_click(delete_button):
                logger.error("Не удалось нажать на кнопку удаления")
                return False
            
            # Ожидание появления и нажатие на кнопку подтверждения
            confirm_button = self.driver_wrapper.safe_find_element(
                By.XPATH, 
                "//button[contains(text(), 'Confirm') or contains(text(), 'Yes') or contains(text(), 'Ok')]",
                timeout=5,
                clickable=True
            )
            
            if confirm_button:
                if self.driver_wrapper.safe_click(confirm_button):
                    logger.info("Подтверждение удаления выполнено")
                    
                    # Ожидаем обновления страницы или уведомления об успешном удалении
                    time.sleep(3)
                    
                    # Проверяем, что объявление исчезло или появилось сообщение об успешном удалении
                    success_indicator = self.driver_wrapper.safe_find_element(
                        By.XPATH, 
                        "//div[contains(@class, 'success') or contains(@class, 'notification')]",
                        timeout=5
                    )
                    
                    if success_indicator:
                        logger.info(f"Получено подтверждение: {success_indicator.text}")
                    
                    # Проверяем, что объявление удалено, перезагрузив страницу
                    driver.refresh()
                    time.sleep(2)
                    
                    # Проверяем, что объявлений стало меньше или они исчезли
                    new_ad_elements = self.driver_wrapper.safe_find_elements(
                        By.XPATH, "//div[contains(@class, 'my-items-list')]/div[contains(@class, 'item')]"
                    )
                    
                    if not new_ad_elements or len(new_ad_elements) < len(ad_elements):
                        logger.info("Объявление успешно удалено")
                        return True
                    else:
                        logger.warning("Количество объявлений не изменилось после удаления")
                        return False
                else:
                    logger.error("Не удалось нажать на кнопку подтверждения")
                    return False
            else:
                logger.error("Кнопка подтверждения удаления не найдена")
                return False
            
        except Exception as e:
            logger.error(f"Ошибка при удалении объявления: {e}")
            logger.debug(traceback.format_exc())
            return False
    
    def load_ad_data(self):
        """Загрузка данных объявления из файла"""
        try:
            ad_data_path = Path(AD_DATA_FILE)
            if not ad_data_path.exists():
                logger.error(f"Файл с данными объявления не найден: {ad_data_path}")
                return None
                
            with open(ad_data_path, 'r', encoding='utf-8') as f:
                ad_data = json.load(f)
                logger.info(f"Данные объявления успешно загружены из {AD_DATA_FILE}")
                
                # Проверка обязательных полей
                required_fields = ["title", "description", "postcode"]
                missing_fields = [field for field in required_fields if field not in ad_data]
                
                if missing_fields:
                    logger.warning(f"В данных объявления отсутствуют обязательные поля: {', '.join(missing_fields)}")
                
                self.ad_data = ad_data
                return ad_data
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка формата JSON в файле данных объявления: {e}")
            return None
        except Exception as e:
            logger.error(f"Не удалось загрузить данные объявления из файла: {e}")
            logger.debug(traceback.format_exc())
            return None
    
    def create_ad(self):
        """Создание нового объявления из предоставленных данных"""
        driver = self.driver_wrapper.driver
        
        # Загрузка данных из файла, если еще не загружены
        if not self.ad_data:
            ad_data = self.load_ad_data()
            if not ad_data:
                logger.error("Не удалось получить данные для создания объявления")
                return False
        else:
            ad_data = self.ad_data
        
        try:
            logger.info("Начало создания нового объявления...")
            
            # Переход на страницу подачи объявления в нужной категории
            category_url = ad_data.get("category_url", "https://www.gumtree.com/post-ad")
            driver.get(category_url)
            
            # Ожидание загрузки формы
            postcode_field = self.driver_wrapper.safe_find_element(By.ID, "postcode", timeout=15)
            if not postcode_field:
                logger.error("Форма создания объявления не загрузилась")
                screenshot_path = f"logs/error_create_form_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                driver.save_screenshot(screenshot_path)
                logger.info(f"Сохранен скриншот: {screenshot_path}")
                return False
            
            # Функция для безопасного заполнения полей формы
            def fill_field(field_id, value, field_type="input", wait_after=0):
                if not value:
                    return True
                
                field = self.driver_wrapper.safe_find_element(By.ID, field_id, timeout=5)
                if field:
                    try:
                        field.clear()
                        field.send_keys(value)
                        if wait_after > 0:
                            time.sleep(wait_after)
                        logger.info(f"Поле {field_id} заполнено: {value[:20]}{'...' if len(str(value)) > 20 else ''}")
                        return True
                    except Exception as e:
                        logger.warning(f"Не удалось заполнить поле {field_id}: {e}")
                        return False
                else:
                    logger.warning(f"Поле {field_id} не найдено")
                    return False
            
            # Заполнение основных полей формы
            fields_to_fill = [
                ("title", ad_data.get("title")),
                ("description", ad_data.get("description")),
                ("price", ad_data.get("price")),
                ("postcode", ad_data.get("postcode"), 1),  # Добавляем задержку после заполнения индекса
                ("contactName", ad_data.get("contact_name")),
                ("phoneNumber", ad_data.get("phone_number"))
            ]
            
            for field_data in fields_to_fill:
                field_id = field_data[0]
                field_value = field_data[1]
                wait_time = field_data[2] if len(field_data) > 2 else 0
                
                fill_field(field_id, field_value, wait_after=wait_time)
            
            # Проверка почтового индекса, если необходимо
            if ad_data.get("postcode"):
                check_button = self.driver_wrapper.safe_find_element(
                    By.XPATH, 
                    "//button[contains(text(), 'Check') or contains(text(), 'Find') or contains(@aria-label, 'check')]",
                    timeout=3,
                    clickable=True
                )
                
                if check_button:
                    self.driver_wrapper.safe_click(check_button)
                    logger.info("Нажата кнопка проверки индекса")
                    time.sleep(2)  # Ожидание проверки индекса
            
            # Заполнение дополнительных полей (специфичные для категории)
            if "additional_fields" in ad_data:
                for field_id, field_value in ad_data["additional_fields"].items():
                    fill_field(field_id, field_value)
            
            # Обработка выпадающих списков
            if "dropdowns" in ad_data:
                for dropdown_id, dropdown_value in ad_data["dropdowns"].items():
                    try:
                        dropdown_element = self.driver_wrapper.safe_find_element(By.ID, dropdown_id, timeout=5)
                        if dropdown_element:
                            dropdown = Select(dropdown_element)
                            dropdown.select_by_visible_text(dropdown_value)
                            logger.info(f"Выпадающий список {dropdown_id} заполнен значением {dropdown_value}")
                        else:
                            logger.warning(f"Выпадающий список {dropdown_id} не найден")
                    except Exception as e:
                        logger.warning(f"Не удалось заполнить выпадающий список {dropdown_id}: {e}")
            
            # Загрузка изображений
            if "image_paths" in ad_data and ad_data["image_paths"]:
                try:
                    upload_button = self.driver_wrapper.safe_find_element(
                        By.XPATH, "//input[@type='file']", timeout=5
                    )
                    
                    if upload_button:
                        # Проверяем существование файлов перед загрузкой
                        valid_images = []
                        for img_path in ad_data["image_paths"]:
                            img_file = Path(img_path)
                            if img_file.exists():
                                valid_images.append(str(img_file.absolute()))
                            else:
                                logger.warning(f"Изображение не найдено: {img_path}")
                        
                        # Загружаем все изображения по очереди
                        for img_path in valid_images:
                            upload_button.send_keys(img_path)
                            logger.info(f"Загружено изображение: {img_path}")
                            time.sleep(2)  # Ждем загрузки изображения
                        
                        if valid_images:
                            logger.info(f"Загружено {len(valid_images)} изображений")
                        else:
                            logger.warning("Не найдено ни одного изображения для загрузки")
                    else:
                        logger.warning("Кнопка загрузки изображений не найдена")
                except Exception as e:
                    logger.warning(f"Не удалось загрузить изображения: {e}")
            
            # Отправка формы
            submit_button = self.driver_wrapper.safe_find_element(
                By.XPATH, 
                "//button[contains(text(), 'Post') or contains(text(), 'Submit') or contains(text(), 'Continue')]",
                timeout=5,
                clickable=True
            )
            
            if not submit_button:
                logger.error("Кнопка отправки формы не найдена")
                screenshot_path = f"logs/error_submit_button_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                driver.save_screenshot(screenshot_path)
                logger.info(f"Сохранен скриншот: {screenshot_path}")
                return False
            
            logger.info("Нажатие на кнопку отправки формы...")
            if not self.driver_wrapper.safe_click(submit_button):
                logger.error("Не удалось нажать на кнопку отправки формы")
                return False
            
            logger.info("Форма отправлена, ожидание подтверждения...")
            time.sleep(5)
            
            # Проверка успешного создания объявления
            if any(keyword in driver.current_url for keyword in ["success", "published", "confirmation"]):
                logger.info("Объявление успешно создано")
                return True
            
            # Проверка на наличие дополнительных шагов или кнопок подтверждения
            for _ in range(2):  # Пробуем найти кнопки подтверждения дважды
                final_buttons = self.driver_wrapper.safe_find_elements(
                    By.XPATH, 
                    "//button[contains(text(), 'Confirm') or contains(text(), 'Publish') or contains(text(), 'Done') or contains(text(), 'Post')]"
                )
                
                if final_buttons:
                    for button in final_buttons:
                        if self.driver_wrapper.safe_click(button):
                            logger.info("Нажата кнопка окончательного подтверждения")
                            time.sleep(3)
                            
                            # Проверяем URL после нажатия
                            if any(keyword in driver.current_url for keyword in ["success", "published", "confirmation"]):
                                logger.info("Объявление успешно создано после дополнительного подтверждения")
                                return True
                
                time.sleep(2)  # Ждем перед повторной попыткой
            
            # Ищем сообщения об успехе на странице
            success_messages = self.driver_wrapper.safe_find_elements(
                By.XPATH, 
                "//div[contains(@class, 'success') or contains(@class, 'notification') or contains(text(), 'successful')]"
            )
            
            if success_messages:
                logger.info(f"Найдено сообщение об успехе: {success_messages[0].text}")
                return True
            
            # Последняя проверка - просто проверим, что мы находимся не на странице редактирования
            if "post-ad" not in driver.current_url and "edit" not in driver.current_url:
                logger.info("Считаем объявление созданным, так как мы покинули страницу создания")
                return True
                
            logger.warning("Не удалось подтвердить успешное создание объявления")
            screenshot_path = f"logs/uncertain_creation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            driver.save_screenshot(screenshot_path)
            logger.info(f"Сохранен скриншот: {screenshot_path}")
            return False
                
        except Exception as e:
            logger.error(f"Ошибка при создании объявления: {e}")
            logger.debug(traceback.format_exc())
            screenshot_path = f"logs/error_creation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            driver.save_screenshot(screenshot_path)
            logger.info(f"Сохранен скриншот: {screenshot_path}")
            return False
    
    def run_job(self):
        """Основная функция для запуска задачи переподачи объявления"""
        logger.info("Запуск автоматической переподачи объявления...")
        
        # Добавление случайной задержки для уменьшения подозрительности
        if RANDOM_DELAY_MAX > 0:
            delay_minutes = random.randint(RANDOM_DELAY_MIN, RANDOM_DELAY_MAX)
            if delay_minutes > 0:
                logger.info(f"Добавлена случайная задержка: {delay_minutes} минут")
                time.sleep(delay_minutes * 60)
        
        # Инициализация драйвера
        try:
            driver = self.driver_wrapper.initialize()
        except Exception as e:
            logger.error(f"Не удалось инициализировать драйвер: {e}")
            logger.debug(traceback.format_exc())
            return False
        
        success = False
        try:
            # Предварительная загрузка данных объявления
            if not self.load_ad_data():
                return False
            # Вход в аккаунт
            if not self.login_to_gumtree():
                logger.error("Не удалось выполнить вход в аккаунт Gumtree")
                return False
            
            # Удаление существующего объявления
            logger.info("Удаление существующего объявления...")
            if not self.delete_ad():
                logger.warning("Не удалось удалить существующее объявление или объявление не найдено")
                # Продолжаем работу, так как отсутствие объявления не критично
            
            # Создание нового объявления
            logger.info("Создание нового объявления...")
            for attempt in range(MAX_RETRIES):
                if self.create_ad():
                    logger.info("Объявление успешно создано")
                    success = True
                    break
                else:
                    logger.warning(f"Попытка {attempt+1}/{MAX_RETRIES} создания объявления не удалась")
                    time.sleep(5)  # Ожидание перед повторной попыткой
            
            if not success:
                logger.error(f"Не удалось создать объявление после {MAX_RETRIES} попыток")
                return False
            
            logger.info("Задача автоматической переподачи объявления выполнена успешно")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка при выполнении задачи переподачи: {e}")
            logger.debug(traceback.format_exc())
            return False
        finally:
            # Закрытие драйвера независимо от результата
            self.driver_wrapper.close()
    
    def start_scheduler(self):
        """Запуск планировщика для регулярного выполнения задачи"""
        logger.info(f"Запуск планировщика с интервалом {RELIST_INTERVAL_HOURS} часов")
        
        # Выполнение задачи сразу при запуске
        self.run_job()
        
        # Настройка регулярного выполнения
        schedule.every(RELIST_INTERVAL_HOURS).hours.do(self.run_job)
        
        try:
            while True:
                schedule.run_pending()
                time.sleep(60)  # Проверка заданий каждую минуту
        except KeyboardInterrupt:
            logger.info("Планировщик остановлен пользователем")
        except Exception as e:
            logger.error(f"Ошибка в планировщике: {e}")
            logger.debug(traceback.format_exc())

def main():
    """Основная функция запуска программы"""
    try:
        # Проверка наличия необходимых переменных окружения
        if not GUMTREE_EMAIL or not GUMTREE_PASSWORD:
            logger.error("Не указаны учетные данные для Gumtree в файле .env")
            return
        
        relister = GumtreeAutoRelister()
        
        # Обработка аргументов командной строки
        if len(sys.argv) > 1:
            if sys.argv[1] == "--once":
                # Запуск однократного выполнения
                logger.info("Запуск однократного выполнения задачи")
                relister.run_job()
            elif sys.argv[1] == "--check":
                # Проверка настроек и данных без выполнения
                logger.info("Проверка настроек и данных...")
                if relister.load_ad_data():
                    logger.info("Проверка прошла успешно. Данные объявления загружены корректно.")
                else:
                    logger.error("Проверка не пройдена. Проблемы с данными объявления.")
            else:
                logger.warning(f"Неизвестный аргумент: {sys.argv[1]}")
                logger.info("Использование: python gumtree_auto_relister.py [--once | --check]")
        else:
            # Запуск планировщика по умолчанию
            relister.start_scheduler()
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        logger.debug(traceback.format_exc())
        return

if __name__ == "__main__":
    main()
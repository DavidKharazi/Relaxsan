
import requests
import zipfile
import os
import xml.etree.ElementTree as ET

# Функция для скачивания файла с Яндекс.Диска по публичному URL
def download_file_from_yandex_disk(public_url, local_filename):
    base_url = "https://cloud-api.yandex.net/v1/disk/public/resources/download"
    response = requests.get(base_url, params={'public_key': public_url})
    download_url = response.json().get('href')
    if not download_url:
        raise Exception("Не удалось получить ссылку на скачивание")
    with requests.get(download_url, stream=True) as r:
        r.raise_for_status()
        with open(local_filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    return local_filename

# Функция для распаковки zip-файла
def unzip_file(zip_filepath, extract_to):
    with zipfile.ZipFile(zip_filepath, 'r') as zip_ref:
        zip_ref.extractall(extract_to)
    print(f"Файлы распакованы в директорию: {extract_to}")
    print(f"Список файлов: {os.listdir(extract_to)}")

# Функция для поиска файла в директории и поддиректориях
def find_file_in_directory(directory, filename):
    for root, dirs, files in os.walk(directory):
        if filename in files:
            return os.path.join(root, filename)
    return None

# Функция для склонения числительных
def declension(quantity):
    quantity = int(quantity)
    if quantity % 10 == 1 and quantity % 100 != 11:
        return f"{quantity} единица"
    elif 2 <= quantity % 10 <= 4 and (quantity % 100 < 10 or quantity % 100 >= 20):
        return f"{quantity} единицы"
    else:
        return f"{quantity} единиц"

# Функция для парсинга XML-файла и извлечения данных
def parse_xml(file_path):
    tree = ET.parse(file_path)
    root = tree.getroot()

    # Словарь для хранения информации о складах
    warehouses = {}
    for warehouse in root.findall('.//Склад'):
        warehouse_id = warehouse.find('Ид').text
        warehouse_name = warehouse.find('Наименование').text
        warehouses[warehouse_id] = warehouse_name

    items = []
    for item in root.findall('.//Товар'):
        item_data = {}
        for child in item:
            if child.tag == "Остатки":
                # Обработка остатков
                stocks = []
                for stock in child.findall('.//Остаток'):
                    stock_id = stock.find('ИдСклада').text if stock.find('ИдСклада') is not None else ""
                    quantity = stock.find('Количество').text if stock.find('Количество') is not None else ""
                    warehouse_name = warehouses.get(stock_id, "Неизвестный склад")
                    formatted_stock = f"На складе {stock_id} ({warehouse_name.replace('(', '').replace(')', '')}): {declension(quantity)}"
                    formatted_stock = formatted_stock.replace("Склад 558 (Магазин Тивали): 1 единица", "На складе 558 (Магазин Тивали): 1 единица")
                    stocks.append(formatted_stock)
                item_data["Остатки"] = stocks
            else:
                item_data[child.tag] = child.text.strip() if child.text else ""
        items.append(item_data)

    return items

# Функция для записи данных в текстовый файл
def write_to_file(data, output_file):
    with open(output_file, 'w', encoding='utf-8') as f:
        for item_data in data:
            for key, value in item_data.items():
                if key == "Остатки":
                    f.write(f"{key}:\n")
                    for stock in value:
                        f.write(f"- {stock}\n")
                else:
                    key = key.replace("Ид", "Идентификатор").replace("КлассКомпрессии", "Класс Компрессии").replace("СтранаПроизв", "Страна Производитель")
                    f.write(f"{key}: {value}\n")
            f.write("\n")

# Основная часть скрипта
if __name__ == "__main__":
    # URL общего доступа к файлу на Яндекс.Диске
    yandex_disk_url = "https://disk.yandex.ru/d/t_m-lxPlt314FA"
    local_zip_file = os.path.join("files", "import.zip")
    extract_to = os.path.join("files", "extracted_files")
    local_xml_file = "import.xml"
    output_file = os.path.join("files", "ТОВАРЫ.txt")

    # Создаем директорию для файлов, если она не существует
    os.makedirs("files", exist_ok=True)

    # Скачиваем файл
    download_file_from_yandex_disk(yandex_disk_url, local_zip_file)

    # Распаковываем zip-файл
    unzip_file(local_zip_file, extract_to)

    # Поиск файла import.xml в распакованной директории
    xml_file_path = find_file_in_directory(extract_to, local_xml_file)
    if not xml_file_path:
        print(f"Файл {local_xml_file} не найден. Проверьте распакованные файлы.")
        exit(1)

    # Парсим XML-файл и записываем данные
    data = parse_xml(xml_file_path)
    write_to_file(data, output_file)

    print(f"Данные успешно записаны в файл {output_file}")

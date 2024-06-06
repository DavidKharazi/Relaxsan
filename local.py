import xml.etree.ElementTree as ET


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
                    stocks.append(f"Склад {stock_id} ({warehouse_name}): {quantity}")
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
                    f.write(f"{key}: {value}\n")
            f.write("\n")


# Основная часть скрипта
if __name__ == "__main__":
    input_file = 'путь к файлу xml'
    output_file = 'output.txt'

    data = parse_xml(input_file)
    write_to_file(data, output_file)

    print(f"Данные успешно записаны в файл {output_file}")

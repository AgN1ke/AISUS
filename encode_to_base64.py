#encode_to_base64.py

import base64

def encode_file_to_base64(file_path):
    """ Функція для кодування файлу в Base64. """
    with open(file_path, 'rb') as file:  # Відкриваємо файл у бінарному режимі
        file_content = file.read()
        encoded_content = base64.b64encode(file_content)  # Кодуємо вміст файлу
        return encoded_content.decode('utf-8')  # Повертаємо закодований вміст як строку UTF-8

if __name__ == '__main__':
    file_path = 'configs/config.ini'  # Шлях до вашого файлу
    encoded_string = encode_file_to_base64(file_path)
    print(encoded_string)  # Виводимо закодований рядок

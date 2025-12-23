import pandas as pd

# Читаем исходный файл
file = 'export-products-20-12-25_13-57-32.csv'
try:
    df = pd.read_csv(file, sep=',', quotechar='"', dtype=str)
    print("--- ПЕРВЫЕ 5 НАЗВАНИЙ ТОВАРОВ ---")
    for name in df['Назва_позиції'].head(5):
        print(f"Name: '{name}'")
except Exception as e:
    print(f"Ошибка: {e}")

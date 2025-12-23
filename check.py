import pandas as pd

try:
    # Читаем наш обновленный файл
    df = pd.read_csv('updated_onyx_sinks.csv', sep=',', quotechar='"', dtype=str)
    
    print("--- ПРОВЕРКА КОЛОНКИ: Пошукові_запити (RU) ---")
    # Выводим первые 3 заполненные ячейки
    print(df['Пошукові_запити'].head(3).to_string(index=False))
    
    print("\n--- ПРОВЕРКА КОЛОНКИ: Пошукові_запити_укр (UA) ---")
    # Выводим первые 3 заполненные ячейки
    print(df['Пошукові_запити_укр'].head(3).to_string(index=False))

except Exception as e:
    print(f"Ошибка чтения: {e}")

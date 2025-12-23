import pandas as pd
import csv

# Загружаем ваш последний экспорт
file_name = 'export-products-21-12-25_10-40-01.csv'
df = pd.read_csv(file_name, dtype=str)

# Находим эталон (Морион)
benchmark_name = "Гранитная мойка для кухни VALESO 5847 ONYX матовый Морион"
benchmark_row = df[df['Назва_позиції'] == benchmark_name].iloc[0]

# Цветовая карта
color_data = {
    'гренадин': 'Коричневий', 'терра': 'Коричневий', 'корич': 'Коричневий',
    'черн': 'Чорний', 'карбон': 'Чорний', 'антрацит': 'Чорний',
    'морион': 'Чорний', 'графит': 'Сірий', 'белоснеж': 'Білий',
    'бел': 'Білий', 'авена': 'Бежевий', 'жасмин': 'Бежевий',
    'топаз': 'Бежевий', 'дюна': 'Бежевий', 'песоч': 'Бежевий',
    'беж': 'Бежевий', 'сер': 'Сірий'
}

# Слоты характеристик, которые копируем (по индексам эталона)
slots = [0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]

for index, row in df.iterrows():
    name = str(row.get('Назва_позиції', '')).lower()
    if 'onyx' in name:
        # Копируем всё из эталона
        for i in slots:
            suffix = "" if i == 0 else f".{i}"
            df.iloc[index, df.columns.get_loc(f'Назва_Характеристики{suffix}')] = benchmark_row[f'Назва_Характеристики{suffix}']
            df.iloc[index, df.columns.get_loc(f'Одиниця_виміру_Характеристики{suffix}')] = benchmark_row[f'Одиниця_виміру_Характеристики{suffix}']
            df.iloc[index, df.columns.get_loc(f'Значення_Характеристики{suffix}')] = benchmark_row[f'Значення_Характеристики{suffix}']
        
        # Цвет ставим отдельно (Слот 1)
        color_val = 'Бежевий'
        for k, v in color_data.items():
            if k in name:
                color_val = v
                break
        df.iloc[index, df.columns.get_loc('Назва_Характеристики.1')] = 'Колір'
        df.iloc[index, df.columns.get_loc('Значення_Характеристики.1')] = color_val

# Сохраняем
df.to_csv('ONYX_ETALON_FINAL.csv', index=False, quoting=csv.QUOTE_ALL)
print("Файл ONYX_ETALON_FINAL.csv успешно создан!")

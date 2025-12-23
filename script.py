import pandas as pd

# Завантажуємо ваш останній файл з помилками
file_path = 'FINAL_GOOGLE_SYNC_VERTICAL - FINAL_GOOGLE_SYNC_VERTICAL.csv.csv'
df = pd.read_csv(file_path, dtype=str)

# 1. Додаємо обов'язкову колонку 'Одиниця_виміру' після 'Валюта'
if 'Одиниця_виміру' not in df.columns:
    # Вставляємо колонку зі значенням 'шт.'
    df.insert(df.columns.get_loc('Валюта') + 1, 'Одиниця_виміру', 'шт.')

# 2. Список колонок, які Пром хоче бачити в кожному рядку (заповнюємо пропуски зверху вниз)
fill_cols = [
    'Назва_позиції', 'Назва_позиції_укр', 'Ціна', 'Валюта', 
    'Наявність', 'Одиниця_виміру', 'Опис', 'Опис_укр', 
    'Пошукові_запити', 'Пошукові_запити_укр'
]

# Заповнюємо порожні клітинки значеннями з першого рядка товару
for col in fill_cols:
    if col in df.columns:
        df[col] = df.groupby('Унікальний_ідентифікатор')[col].ffill()

# 3. На всякий випадок ще раз перевіряємо наявність '+' (виправляємо #ERROR!)
if 'Наявність' in df.columns:
    df['Наявність'] = df['Наявність'].replace('#ERROR!', '+')

# Зберігаємо фінальний, повністю заповнений файл
df.to_csv('FINAL_FIXED_FOR_PROM_FULL.csv', index=False, encoding='utf-8')
print("Готово! Створено файл: FINAL_FIXED_FOR_PROM_FULL.csv")

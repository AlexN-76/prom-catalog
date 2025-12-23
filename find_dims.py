import pandas as pd

try:
    df = pd.read_csv('updated_onyx_sinks.csv', sep=',', quotechar='"', dtype=str)
    
    print("--- ПОИСК РАЗМЕРОВ В ФАЙЛЕ ---")
    
    # Берем первую строку (первый товар)
    row = df.iloc[0]
    
    found_width = False
    found_depth = False
    found_color = False
    
    # Перебираем все возможные колонки характеристик
    for i in range(50):
        suffix = f".{i}" if i > 0 else ""
        col_name = f"Назва_Характеристики{suffix}"
        val_name = f"Значення_Характеристики{suffix}"
        
        if col_name in row:
            name = str(row[col_name])
            value = str(row[val_name])
            
            if "Ширина" in name and "шафи" not in name: # Исключаем "Ширина шафи"
                print(f"[OK] Ширина найдена в колонке: {col_name} | Значение: {value}")
                found_width = True
            if "Глибина" in name and "чаші" not in name: # Исключаем глубину чаши
                print(f"[OK] Глубина найдена в колонке: {col_name} | Значение: {value}")
                found_depth = True
            if "Колір" in name:
                print(f"[OK] Цвет найден в колонке: {col_name} | Значение: {value}")
                found_color = True

    if not found_width: print("[FAIL] Ширина НЕ найдена!")
    if not found_depth: print("[FAIL] Глубина НЕ найдена!")
    if not found_color: print("[FAIL] Цвет НЕ найден!")

except Exception as e:
    print(f"Ошибка: {e}")

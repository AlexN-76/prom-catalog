import re

input_file = 'updated_onyx_sinks_fixed.csv'
output_file = 'updated_onyx_ready_for_prom.csv'

try:
    with open(input_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # Берем первую строку (заголовки)
    headers = lines[0]
    
    # Убираем .1, .2, .10 из названий колонок
    # Регулярное выражение ищет точки с цифрами в конце названий полей
    new_headers = re.sub(r'\.\d+', '', headers)
    
    lines[0] = new_headers
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.writelines(lines)
        
    print(f"Готово! Файл '{output_file}' создан.")
    print("Все заголовки очищены (Назва_Характеристики.1 -> Назва_Характеристики).")
    print("Теперь Пром должен распознать файл АВТОМАТИЧЕСКИ.")

except Exception as e:
    print(f"Ошибка: {e}")

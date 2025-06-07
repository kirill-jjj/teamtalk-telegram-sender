import os
from glob import glob

LOCALE_DIR = os.path.join('bot', 'locales')
DOMAIN = 'messages'
LANGS = ['ru']

env = Environment()

def extract_messages(target, source, env):
    print(f"--- Извлечение строк в {LOCALE_DIR}/{DOMAIN}.pot ---")
    os.makedirs(LOCALE_DIR, exist_ok=True)
    command = f'pybabel extract -F babel.cfg -k _ -o {LOCALE_DIR}/{DOMAIN}.pot .'
    result = env.Execute(command)
    if result != 0:
        print("ОШИБКА: Не удалось извлечь строки.")
        Exit(result)
    return None

def update_catalogs(target, source, env):
    print("--- Обновление .po каталогов ---")
    for lang in LANGS:
        po_file = os.path.join(LOCALE_DIR, lang, 'LC_MESSAGES', f'{DOMAIN}.po')
        if not os.path.exists(po_file):
            print(f"Создание каталога для языка: {lang}")
            command = f'pybabel init -i {LOCALE_DIR}/{DOMAIN}.pot -d {LOCALE_DIR} -l {lang} -D {DOMAIN}'
        else:
            print(f"Обновление каталога для языка: {lang}")
            command = f'pybabel update -i {LOCALE_DIR}/{DOMAIN}.pot -d {LOCALE_DIR} -l {lang} -D {DOMAIN}'
        result = env.Execute(command)
        if result != 0:
            print(f"ОШИБКА: Не удалось обновить каталог для {lang}.")
            Exit(result)
    return None

def compile_catalogs(target, source, env):
    print("--- Компиляция .mo файлов ---")
    command = f'pybabel compile -d {LOCALE_DIR} -D {DOMAIN} -f'
    result = env.Execute(command)
    if result != 0:
        print("ОШИБКА: Не удалось скомпилировать каталоги.")
        Exit(result)
    return None

def clean_generated(target, source, env):
    print("--- Очистка сгенерированных файлов ---")
    for path in glob(f'{LOCALE_DIR}/**/LC_MESSAGES/*.mo', recursive=True):
        os.remove(path)
    pot_file = os.path.join(LOCALE_DIR, f'{DOMAIN}.pot')
    if os.path.exists(pot_file):
        os.remove(pot_file)
    return None

env.Alias('extract', [], Action(extract_messages))
env.Alias('update', [], Action(update_catalogs))
env.Alias('compile', [], Action(compile_catalogs))
env.Alias('clean', [], Action(clean_generated))
Default(env.Alias('compile'))

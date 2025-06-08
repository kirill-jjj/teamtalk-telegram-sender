import os
import sys
from glob import glob

# --- Конфигурация ---
LOCALE_DIR = os.path.join('bot', 'locales')
DOMAIN = 'messages'
POT_FILE = os.path.join(LOCALE_DIR, f'{DOMAIN}.pot')

SOURCE_FILES = glob('bot/**/*.py', recursive=True)

PROJECT_NAME = "TeamTalk-Telegram-Sender"
PROJECT_VERSION = "0.2.0" # Укажите актуальную версию
COPYRIGHT_HOLDER = "kirill-jjj"
BUGS_ADDRESS = "kirillkolovi@gmail.com"
AUTHOR_INFO = "kirill-jjj <kirillkolovi@gmail.com>"

PYTHON_EXE = sys.executable
PYBABEL_CMD = os.path.join(os.path.dirname(PYTHON_EXE), 'pybabel')

env = Environment()

# --- Цели (Targets) и их сборка ---

# 1. Цель: messages.pot (шаблон перевода)
pot_target = env.Command(
    target=POT_FILE,
    source=SOURCE_FILES,
    action=(
        f'"{PYBABEL_CMD}" extract -F babel.cfg -k _ -o $TARGET $SOURCES '
        f'--project="{PROJECT_NAME}" '
        f'--version="{PROJECT_VERSION}" '
        f'--copyright-holder="{COPYRIGHT_HOLDER}" '
        f'--msgid-bugs-address="{BUGS_ADDRESS}" '
    )
)
env.Alias('extract', pot_target)
env.Precious(pot_target) # Защита от случайного удаления


# 2. Цели: messages.po (файлы переводов для каждого языка)
po_targets = []
try:
    # Динамически ищем все папки с языками (ru, en и т.д.)
    langs = [d.name for d in os.scandir(LOCALE_DIR) if d.is_dir()]
except FileNotFoundError:
    langs = [] 

for lang in langs:
    po_file = os.path.join(LOCALE_DIR, lang, 'LC_MESSAGES', f'{DOMAIN}.po')
    
    update_cmd = f'"{PYBABEL_CMD}" update -i {POT_FILE} -d {LOCALE_DIR} -D {DOMAIN} -l {lang}'
    init_cmd = f'"{PYBABEL_CMD}" init -i {POT_FILE} -d {LOCALE_DIR} -D {DOMAIN} -l {lang}'
    
    command_to_run = init_cmd if not os.path.exists(po_file) else update_cmd
    
    po_target = env.Command(
        target=po_file,
        source=pot_target, # .po файл НАПРЯМУЮ зависит от .pot файла
        action=command_to_run
    )
    po_targets.append(po_target)

env.Alias('update', po_targets)


# 3. Цели: messages.mo (скомпилированные переводы)
mo_targets = []
for po_target in po_targets:
    mo_target = env.Command(
        target=str(po_target).replace('.po', '.mo'),
        source=po_target, # .mo файл НАПРЯМУЮ зависит от .po файла
        action=f'"{PYBABEL_CMD}" compile -d {LOCALE_DIR} -D {DOMAIN} -f'
    )
    mo_targets.append(mo_target)

compile_alias = env.Alias('compile', mo_targets)


# 4. Цель: clean (очистка)
def clean_action(target, source, env):
    print("--- Очистка сгенерированных файлов ---")
    files_to_remove = glob(f'{LOCALE_DIR}/**/*.mo', recursive=True)
    files_to_remove.append(POT_FILE)
    
    for file_path in files_to_remove:
        if os.path.exists(file_path):
            print(f"Удаление {file_path}")
            os.remove(file_path)

env.Alias('clean', [], Action(clean_action))


# Команда по умолчанию: скомпилировать все
Default(compile_alias)
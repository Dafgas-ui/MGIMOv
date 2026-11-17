"""Small, immutable text attachments in the same transaction and SQLite as Coursework."""
import base64
import binascii
import re
import uuid

from .brs.service import fail

MAX_FILE_BYTES = 65_536


def decode_file(file):
    if not isinstance(file, dict) or set(file) != {'name', 'content'}:
        fail(422, 'Проверьте вложение.')
    name, encoded = file['name'], file['content']
    if (not isinstance(name, str) or not re.fullmatch(r'[\w][\w -]{0,74}\.(?:txt|md)', name, re.I)
            or re.fullmatch(r'con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³]', name.rsplit('.', 1)[0].rstrip(), re.I)
            or not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_FILE_BYTES + 2) // 3)):
        fail(422, 'Допустимы текстовые файлы TXT и MD до 64 КиБ.')
    try:
        content = base64.b64decode(encoded, validate=True)
        decoded = content.decode('utf-8')
    except (UnicodeError, ValueError, binascii.Error):
        fail(422, 'Файл должен содержать текст UTF-8.')
    if not 1 <= len(content) <= MAX_FILE_BYTES or any(
        not (char.isprintable() or char in '\t\r\n') for char in decoded
    ):
        fail(422, 'Файл должен содержать текст UTF-8 до 64 КиБ.')
    return name, content


def store_files(db, assignment, files, *, course=None, attempt=None):
    if not isinstance(files, list) or not 1 <= len(files) <= 2:
        fail(422, 'Можно прикрепить до двух файлов.')
    decoded = [decode_file(file) for file in files]
    if course is None:
        first = db.execute('SELECT count(*) FROM coursework_files WHERE assignment_id=? AND course_id IS NULL',
                           (assignment,)).fetchone()[0] + 1
        if first + len(decoded) > 3:
            fail(409, 'Достигнут предел материалов задания.')
    else:
        first = 1
    db.executemany('INSERT INTO coursework_files VALUES (?,?,?,?,?,?,?)',
                   ((uuid.uuid4().hex, assignment, course, attempt, slot, name, content)
                    for slot, (name, content) in enumerate(decoded, first)))


def list_files(db, assignment, course=None):
    return [dict(row) for row in db.execute("""SELECT id,name,length(content) AS size,attempt_no
        FROM coursework_files WHERE assignment_id=? AND course_id IS ? ORDER BY attempt_no,slot""",
        (assignment, course))]

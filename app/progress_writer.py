"""Best-effort progress reporting; actual production checkpoints remain strict."""
import json
import os
import pathlib
import sys
import time
import uuid

def atomic_json(path, data):
    """Write essential state atomically; retry short Windows sharing conflicts."""
    path = pathlib.Path(path)
    tmp = path.with_name(path.name + '.' + str(os.getpid()) + '.' + uuid.uuid4().hex + '.tmp')
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        for attempt in range(30):
            try:
                tmp.replace(path)
                return
            except PermissionError:
                if attempt == 29: raise
                time.sleep(.1)
    finally:
        try: tmp.unlink(missing_ok=True)
        except OSError: pass

def write_progress(path, data):
    path = pathlib.Path(path)
    tmp = path.with_name(path.name + '.' + str(os.getpid()) + '.' + uuid.uuid4().hex + '.tmp')
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        for attempt in range(5):
            try:
                tmp.replace(path)
                return True
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(.05 * (attempt + 1))
    except OSError as exc:
        print('Progress update unavailable; production continues: ' + str(exc), file=sys.stderr, flush=True)
        return False
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass

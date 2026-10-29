"""Private, short-lived checkpoints for interrupted report generation.

Only a stage whose caller has finished checking it is reusable. A successful
report consumes its checkpoints, so deliberate regeneration remains fresh.
"""
import copy
import hashlib
import json
import time
import uuid
from pathlib import Path
from . import store


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class Checkpoints:
    def __init__(self, paper_id):
        self.folder = store.data_dir() / 'drafts'
        self.folder.mkdir(exist_ok=True)
        self.prefix = paper_id + '-checkpoint-'
        self.pending = None
        self.used = set()
        for path in self.folder.glob(self.prefix + '*.json'):
            if time.time() - path.stat().st_mtime > 7 * 86400:
                path.unlink(missing_ok=True)

    def key(self, stage, config, system, prompt, schema, images):
        # Image bytes, not temporary paths: a recrop must invalidate reuse.
        return digest([1, stage, config, system, prompt, schema,
                       [hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in images]])

    def advance(self):
        if self.pending:
            path, result = self.pending
            temporary = path.with_name(uuid.uuid4().hex + '.tmp')
            temporary.write_text(json.dumps(result, ensure_ascii=False))
            temporary.replace(path)
            self.pending = None

    def get(self, key):
        path = self.folder / (self.prefix + key + '.json')
        self.used.add(path)
        try:
            value = json.loads(path.read_text())
            if not all(k in value for k in ('value', 'usage', 'model', 'provider')):
                return None
            result = copy.deepcopy(value)
            result['usage'] = {'checkpoint_reused': True, 'completion_tokens': 0}
            return result
        except (OSError, ValueError, TypeError):
            return None

    def stage(self, key, result):
        path = self.folder / (self.prefix + key + '.json')
        self.used.add(path)
        self.pending = (path, copy.deepcopy(result))

    def finish(self, success):
        # The last returned result might have failed semantic validation.
        if self.pending:
            self.pending[0].unlink(missing_ok=True)
        self.pending = None
        if success:
            for path in self.used:
                path.unlink(missing_ok=True)

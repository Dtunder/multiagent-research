import importlib.util
import pathlib
import sys
import tempfile
import types
import unittest

# Pure unit tests do not touch network/config parsing. Stub optional runtime deps.
feedparser = types.ModuleType('feedparser')
feedparser.parse = lambda *_a, **_k: None
sys.modules['feedparser'] = feedparser

requests = types.ModuleType('requests')
class _Session:
    def __init__(self): self.headers = {}
requests.Session = _Session
sys.modules['requests'] = requests

yaml = types.ModuleType('yaml')
yaml.safe_load = lambda *_a, **_k: {}
sys.modules['yaml'] = yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ai_radar', ROOT / 'ai_radar.py')
mod = importlib.util.module_from_spec(spec)
sys.modules['ai_radar'] = mod
spec.loader.exec_module(mod)


class RadarTests(unittest.TestCase):
    def test_canonical_url_strips_tracking(self):
        self.assertEqual(mod.canonical_url('https://Example.com/a/?utm_source=x&id=3#z'), 'https://example.com/a?id=3')

    def test_title_similarity(self):
        a = 'New open source reasoning model released by Example AI'
        b = 'Example AI releases new open-source reasoning model'
        self.assertGreater(mod.title_similarity(a, b), 0.55)

    def test_dedupe_url(self):
        x = mod.Item('x', 'hello model', 'https://x.test/1?utm_source=a', mod.iso()).finalize()
        y = mod.Item('rss', 'hello model', 'https://x.test/1', mod.iso()).finalize()
        self.assertEqual(len(mod.dedupe([x, y], 0.9)), 1)

    def test_classify(self):
        x = mod.Item('arxiv', 'A new agentic tool-use benchmark', 'https://a.test', mod.iso()).finalize()
        self.assertEqual(mod.classify(x), 'Agents')

    def test_atomic_write(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / 'x' / 'state.json'
            mod.atomic_write(p, 'abc')
            self.assertEqual(p.read_text(encoding='utf-8'), 'abc')


if __name__ == '__main__':
    unittest.main()

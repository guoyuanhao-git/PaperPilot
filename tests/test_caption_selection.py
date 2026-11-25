import unittest
from unittest.mock import patch
import test_core
from paperpilot import store, documents, caption_selection


class CaptionSelection(unittest.TestCase):
    setUp = test_core.Core.setUp
    tearDown = test_core.Core.tearDown

    def test_labels_do_not_require_punctuation_but_reject_prose(self):
        for text, expected in [('Figure 1 VLA-Rolling reuses tails.', ('figure','1')),
                               ('Figure3 Action tails require refinement.', ('figure','3')),
                               ('Table 8 N* Locally Optimal Test.', ('table','8')),
                               ('Table 2 results under distribution shift', ('table','2'))]:
            self.assertEqual(documents.figure_label(text), expected)
        for text in ('Figure 2 shows the results.', 'Table 6 showed that the method works.', 'As shown in Figure 3.'):
            self.assertIsNone(documents.figure_label(text))

    def test_selected_and_manual_caption_translation_is_cached_and_does_not_save_crop(self):
        p=documents.ingest(test_core.pdf(),'fixture.pdf')
        data=caption_selection.page_text(p['id'],1)
        text=next(l['text'] for l in data['lines'] if l['text'].startswith('Figure'))
        with patch('paperpilot.providers.generate',return_value={'value':{'translation':'Figure 1 测试图表。'}}) as model:
            result=caption_selection.translate(p['id'],1,text)
            self.assertEqual(caption_selection.translate(p['id'],1,text),result)
            model.assert_called_once()
            self.assertEqual(model.call_args.args[0]['deepseek']['thinking'],'disabled')
            with patch('paperpilot.caption_selection.page_text',side_effect=AssertionError('Must not require extracted text')):
                manual='Figure 2: Corrected efficiency–performance comparison'
                edited=caption_selection.translate(p['id'],1,manual)
                self.assertEqual(edited['original'],manual)
                self.assertEqual(caption_selection.translate(p['id'],1,manual),edited)
                self.assertEqual(model.call_count,2)
            for page,text in [(99,manual),(True,manual),(1,''),(1,'x'*1601)]:
                with self.assertRaises(ValueError):caption_selection.translate(p['id'],page,text)
            self.assertEqual(model.call_count,2)
        self.assertEqual(store.get('paper',p['id'])['figures'],p['figures'])
        with self.assertRaises(ValueError):caption_selection.page_text(p['id'],99)
        p['pdf_released']=True;store.save('paper',p)
        with self.assertRaises(ValueError):caption_selection.page_text(p['id'],1)
        with self.assertRaises(ValueError):caption_selection.translate(p['id'],1,text)

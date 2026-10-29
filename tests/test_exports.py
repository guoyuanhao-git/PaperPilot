import unittest
from paperpilot import exports


class ExportModes(unittest.TestCase):
    def test_pdf_requires_report_but_ppt_is_independent_of_reading_mode(self):
        for mode in ('overview', 'detailed', 'deep'):
            paper = {'report': {'mode': mode}}
            exports.validate_request(paper, 'pdf')
            exports.validate_request(paper, 'pptx')
        exports.validate_request({}, 'pptx')
        with self.assertRaisesRegex(ValueError, '请先生成'):
            exports.validate_request({}, 'pdf')
        with self.assertRaisesRegex(ValueError, '原文 PDF'):
            exports.validate_request({'metadata_only': True}, 'pptx')
        with self.assertRaises(ValueError):
            exports.validate_request({}, 'html')

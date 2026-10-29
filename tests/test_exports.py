import unittest
from unittest.mock import patch
from paperpilot import exports


class ExportModes(unittest.TestCase):
    def test_pdf_requires_saved_report_for_every_reading_mode(self):
        for mode in ('overview', 'detailed', 'deep'):
            exports.validate_request({'report': {'mode': mode}}, 'pdf')
        with self.assertRaisesRegex(ValueError, '请先生成'):
            exports.validate_request({}, 'pdf')

    def test_removed_ppt_generation_is_rejected_before_rendering(self):
        for paper in ({}, {'report': {'mode': 'deep'}}, {'metadata_only': True}, {'pdf_released': True}):
            for format in ('pptx', 'html'):
                with self.subTest(paper=paper, format=format), patch('paperpilot.exports.subprocess.run') as render:
                    with self.assertRaisesRegex(ValueError, '仅支持 PDF'):
                        exports.export('fixture', format, lambda _: None, paper={'id': 'fixture', **paper})
                    render.assert_not_called()

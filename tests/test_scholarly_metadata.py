import unittest
import json
from unittest.mock import patch
from paperpilot import scholarly_metadata as m

class ScholarlyMetadata(unittest.TestCase):
 def test_venue_requires_explicit_publication_not_submission(self):
  paper={'source_url':'https://arxiv.org/abs/2610.12978'}
  info={'original_title':'Paper Title','authors':[{'name':'Zihao Pan'}]}
  def xml(comment):return '<feed xmlns="http://www.w3.org/2005/Atom" xmlns:x="http://arxiv.org/schemas/atom"><entry><title>Paper Title</title><x:comment>'+comment+'</x:comment></entry></feed>'
  with patch.object(m,'fetch',return_value=xml('Accepted at CVPR 2026')):
   self.assertEqual(m.venue(paper,info)['name'],'CVPR 2026')
  for comment in ('Submitted to CVPR 2026','Not accepted at CVPR 2026','Preprint'):
   with patch.object(m,'fetch',side_effect=[xml(comment),'{"message":{"items":[]}}']):
    self.assertIsNone(m.venue(paper,info))
  with patch.object(m,'fetch',side_effect=[xml('Accepted at CVPR').replace('Paper Title','Different Paper'),'{"message":{"items":[]}}']):
   self.assertIsNone(m.venue(paper,info))

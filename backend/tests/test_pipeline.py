"""No live internet required. Tests are explicitly synthetic fixtures, never dashboard data."""
import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
import db
import signals
import export_static

class ResearchTests(unittest.TestCase):
    def test_category_rules(self):
        examples=[('Boxy T-Shirt','Tees & Tops'),('Fleece Pullover','Fleece & Outerwear'),('9TWENTY Adjustable Hat','Headwear'),('Mug','Other Apparel')]
        for name,group in examples:
            with self.subTest(name=name):
                self.assertEqual(signals.public_category({'title':name,'vendor':'','product_type':'','tags':[]}),group)
    def test_no_arbitrary_scores(self):
        no_stores={'stores':[],'brand_matrix':[]}
        no_news={'posts':[],'themes':[]}
        no_weather={'stockout_pct':None}
        cards=signals.build_brief(no_stores,no_news,no_weather)
        self.assertEqual(len(cards),4)
        for card in cards:
            self.assertNotIn('score',card)
            self.assertNotIn('rank',card)
            self.assertIn('observed',card)
            self.assertIn('inferred',card)
    def test_category_match_on_real_shape(self):
        product={'title':"Women's Cropped Tee",'vendor':'Sportiqe','product_type':'','tags':[],'price':45,'url':'https://example.com/p/1','sizes':[], 'image_url':None}
        s=signals._store_stats('Example Store','example.com',[product],'2026-11-20T14:00:00Z',False)
        self.assertEqual(s['category_counts']['Tees & Tops'],1)
        self.assertEqual(s['products'][0]['category_group'],'Tees & Tops')
        self.assertIsNone(s['products'][0]['image_url'])
    def test_rival_variant_sizes(self):
        product={'id':10,'title':'Hoodie','handle':'hoodie','images':[], 'options':[{'name':'Size'}],
                 'variants':[{'option1':'M','price':'55.00','available':False}, {'option1':'L','price':'55.00','available':True}]}
        x=signals.parse_rival(product,'example.com')
        self.assertEqual(x['sizes'],[{'size':'M','available':False},{'size':'L','available':True}])
    def test_sqlite_rival_sizes(self):
        with tempfile.TemporaryDirectory() as t:
            with patch.object(db,'DB_PATH',str(Path(t)/'test.db')):
                db.init_db()
                row={'shopify_id':1,'title':'A hoodie','handle':'hoodie','vendor':'Example','product_type':'Hoodie','tags':[],
                     'price':45,'product_url':'https://example.com/hoodie','image_url':None,'sizes':[{'size':'M','available':False}]}
                db.replace_rival_products('example.com',[row])
                self.assertEqual(db.get_rival_products('example.com')[0]['sizes'],row['sizes'])
    def test_snapshot_no_fake_data(self):
        with tempfile.TemporaryDirectory() as t:
            with patch.object(db,'DB_PATH',str(Path(t)/'empty.db')):
                x=export_static.snapshot_payload()
                self.assertFalse(x['data_available'])
                self.assertIsNone(x['captured_at'])
                self.assertEqual(x['skus']['total'],0)
                path=Path(t)/'snapshot.json'
                export_static.write_snapshot(x,[path])
                check=json.loads(path.read_text())
                self.assertFalse(check['data_available'])

if __name__=='__main__':unittest.main()

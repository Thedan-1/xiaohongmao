import unittest
from unittest.mock import patch
import lead_review


class ReviewTests(unittest.TestCase):
    def test_invalid_quote_drops_only_that_person(self):
        items=[dict(profile_url=f'u{i}',source_text='需要工具',title='BIM',kind='reply') for i in range(2)]
        def fake(s,d,l,validate,**kwargs):
            return validate({'results':[dict(id=str(i),decision='keep',category='need',evidence=q,reason='明确') for i,q in enumerate(['需要工具','不存在的证据'])]})
        with patch.object(lead_review.ai,'complete',side_effect=fake):
            rows=lead_review.refine('BIM','土建工具',items)
        self.assertEqual([r['decision'] for r in rows],['keep','skip'])

    def test_dedupe_prefers_evidence_and_excludes_own_and_blocked(self):
        rows=[dict(profile_url=p,decision=d,category=c) for p,d,c in [('a','skip','unclear'),('a','keep','need'),('me','keep','need'),('blocked','keep','provider')]]
        self.assertEqual(lead_review.unique_people(rows,'me',['blocked']),[rows[1]])

    def test_resume_keeps_only_unread_relevant_notes_from_same_topic(self):
        import sqlite3,json
        from comment_flow import init
        con=sqlite3.connect(':memory:');init(con)
        sources=[{'note_url':f'https://www.xiaohongshu.com/explore/n{i}'} for i in range(3)]
        report={'candidate_sources':sources,'title_decisions':[{'id':str(i),'relevant':i!=2} for i in range(3)]}
        con.execute('INSERT INTO comment_runs(id,topic,report) VALUES(1,?,?)',('BIM',json.dumps(report)))
        con.execute('INSERT INTO comment_captures(run_id,note_key) VALUES(1,?)',('n0',))
        pending,seen=lead_review.unused_sources(con,'BIM')
        self.assertEqual(pending,[sources[1]]);self.assertEqual(seen,{'n0'})
        self.assertEqual(lead_review.unused_sources(con,'LOL'),([],set()))
        con.close()

if __name__=='__main__':unittest.main()

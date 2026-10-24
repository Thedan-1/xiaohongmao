import threading,unittest
from contextlib import nullcontext
from unittest.mock import Mock,patch
import app,studio,batch_comments,test_studio
from test_batch_comments import capture

class ReadDedupTests(unittest.TestCase):
    setUp=test_studio.StudioTests.setUp
    tearDown=test_studio.StudioTests.tearDown

    def test_account_switch_url_aliases_and_changed_queries_do_not_reread_same_project(self):
        other=studio.request(app,{'action':'create'})['project_id'];reads=[]
        worker=Mock();worker.browser_operation.side_effect=lambda *a:nullcontext()
        worker.page.locator.return_value.filter.return_value.first.get_attribute.return_value='/user/profile/accountA'
        def read(page,row,stop):
            from urllib.parse import urlsplit
            i=int(urlsplit(row['note_url']).path.rsplit('/',1)[-1][1:]);reads.append(i);return capture(i)
        def find(pid,rows,count,query):
            def link(rid):
                with app.connect() as con:con.execute('INSERT INTO studio_runs(project_id,run_id) VALUES(?,?)',(pid,rid))
            with patch.object(batch_comments.adapter,'collect_search',return_value=rows):
                batch_comments.find(worker,{'topic':query,'criteria':'找创作者','count':count,'queries':[query],'project_id':pid,'on_run_created':link},threading.Event(),app.connect,Mock(),Mock())
        row=lambda i:{'note_url':capture(i)['note_url'],'note_title':'相关作品'}
        with patch.object(batch_comments.ai,'budget',return_value={'reserved_or_peak_cost':0}),patch('comment_flow.screen_notes',side_effect=lambda t,ns:[{'id':n['id'],'relevant':True} for n in ns]),patch.object(batch_comments.note_collector,'collect_ready',side_effect=read),patch.object(batch_comments,'decide',side_effect=lambda t,g,ns:[{'id':batch_comments.compact(n)['id'],'relevant':True,'contacts':[],'author_contact':False} for n in ns]):
            find(1,[row(0),row(1)],2,'LOL混剪')
            self.assertEqual(reads,[0,1])
            worker.page.locator.return_value.filter.return_value.first.get_attribute.return_value='/user/profile/accountB'
            find(1,[row(0),{'note_url':'https://www.xiaohongshu.com/search_result/n1?xsec_token=changed','note_title':'相关作品'},row(2),row(2)],1,'英雄联盟精彩集锦')
            self.assertEqual(reads,[0,1,2],'同项目换号、换词、链接参数变化不应重读n0/n1')
            find(other,[row(0)],1,'LOL混剪')
            self.assertEqual(reads,[0,1,2,0],'独立新项目可以重新采集，不能暗中共用旧项目进度')
        with app.connect() as con:
            self.assertEqual(len(studio.state(con,1)['notes']),3)
            self.assertEqual(len(studio.state(con,other)['notes']),1)

if __name__=='__main__':unittest.main()

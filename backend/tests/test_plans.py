import asyncio
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, AsyncMock

SCRATCH=Path(__file__).resolve().parents[2]/'work'
SCRATCH.mkdir(exist_ok=True)
TEMP=tempfile.TemporaryDirectory(prefix='plan-tests-',dir=SCRATCH,ignore_cleanup_errors=True)
os.environ['JOB_RADAR_DATA']=TEMP.name

from app import db,plans,execution,llm,conductor
from app.config import DEFAULT_SETTINGS,save_global_settings,load_settings,save_settings
from app.plan_context import scope
from app.models import Job
from app.scheduler import Scheduler


class PlanTests(unittest.TestCase):
    def test_known_old_post_filtered_before_ai(self):
        from app.collectors import REGISTRY
        self.job.needs_enrich=True
        self.job.published_at='2020-01-01'
        with scope(self.p['id']),patch.object(REGISTRY['boss'],'collect',new=AsyncMock(return_value=[self.job])):
            result=asyncio.run(execution.run_source('boss'))
            self.assertEqual(result['kept'],0)
            self.assertEqual(db.get_job(self.job.id)['status'],'filtered')
            self.assertEqual(db.jobs_to_enrich(),[])

    def test_cancel_before_start_releases_only_target_plan(self):
        async def check():
            scheduler=Scheduler()
            async def pending(*args): await asyncio.sleep(60)
            with patch.object(scheduler,'_run',new=pending),patch.object(db,'runs_today',return_value=0):
                with scope(self.p['id']): self.assertTrue(scheduler.trigger('boss'))
                with scope(self.q['id']): self.assertTrue(scheduler.trigger('boss'))
                task=scheduler.tasks[(self.p['id'],'boss')]
                self.assertEqual(scheduler.cancel(self.p['id']),1)
                await asyncio.gather(task,return_exceptions=True)
                self.assertNotIn((self.p['id'],'boss'),scheduler.tasks)
                self.assertIn((self.q['id'],'boss'),scheduler.tasks)
                await scheduler.stop()
        asyncio.run(check())

    def test_partial_collection_preserved_and_reported(self):
        from app.collectors import CollectorError,REGISTRY
        with scope(self.p['id']), patch.object(REGISTRY['boss'],'collect',new=AsyncMock(side_effect=CollectorError('login','请登录',[self.job]))):
            result=asyncio.run(execution.run_source('boss'))
            self.assertFalse(result['ok'])
            self.assertEqual(result['kind'],'login')
            self.assertIsNotNone(db.get_job(self.job.id))

    def test_unchanged_duplicate_keeps_evaluation(self):
        with scope(self.p['id']):
            db.upsert_jobs([self.job])
            db.update_job(self.job.id,{'enriched':1,'score':88,'verdict':'recommend'})
            db.upsert_jobs([self.job,self.job])
            self.assertEqual(db.get_job(self.job.id)['score'],88)
            self.assertEqual(db.get_job(self.job.id)['enriched'],1)

    def test_reevaluation_invalidates_old_response(self):
        from fastapi.testclient import TestClient
        from app.main import app
        with scope(self.p['id']):
            db.upsert_jobs([self.job])
            old=plans.get()['revision']
            r=TestClient(app).post('/api/plans/'+self.p['id']+'/reevaluate')
            self.assertEqual(r.status_code,200)
            db.update_evaluation(self.job.id,{'score':99,'evaluated':1},old)
            self.assertIsNone(db.get_job(self.job.id)['score'])

    def test_plan_changed_during_collection_does_not_accept_old_results(self):
        from app.collectors import REGISTRY
        async def collect(*args):
            plans.update(self.p['id'],{'criteria':{'keywords':['销售']}})
            return [self.job]
        with scope(self.p['id']),patch.object(REGISTRY['boss'],'collect',new=collect):
            result=asyncio.run(execution.run_source('boss'))
            self.assertFalse(result['ok'])
            self.assertIsNone(db.get_job(self.job.id))

    def test_metadata_edit_does_not_strand_pending_jobs(self):
        with scope(self.p['id']):
            db.upsert_jobs([self.job])
            plans.update(self.p['id'],{'name':'新的名称'})
            rev=plans.get()['revision']
            db.update_evaluation(self.job.id,{'score':75,'evaluated':1},rev)
            self.assertEqual(db.get_job(self.job.id)['score'],75)

    @classmethod
    def setUpClass(cls):
        db.init()

    def setUp(self):
        db.conn().execute('DELETE FROM collector_cache')
        db.conn().commit()
        self.p=plans.create({'name':'厦门 Python 全职','person':'小明','criteria':{'keywords':['Python'],'cities':['厦门'],'job_types':['fulltime'],'salary_min_k':0}})
        self.q=plans.create({'name':'上海销售','person':'小红','criteria':{'keywords':['销售'],'cities':['上海'],'job_types':['fulltime']}})
        self.job=Job(source='boss',external_id=self.p['id'],title='Python 工程师',url='https://www.zhipin.com/job_detail/test.html',city='厦门',company='测试公司',job_type='fulltime',description='岗位职责 Python 开发。'*30,published_at='2026-10-24')

    def test_shared_facts_independent_results_and_actions(self):
        with scope(self.p['id']):
            self.assertEqual(db.upsert_jobs([self.job]),[self.job.id])
            db.update_job(self.job.id,{'status':'starred','score':90,'verdict':'recommend','enriched':1})
        with scope(self.q['id']):
            self.assertEqual(db.query_jobs(),[])
            self.assertIsNone(db.get_job(self.job.id))
            self.assertEqual(db.upsert_jobs([self.job]),[])
            j=db.get_job(self.job.id)
            self.assertEqual(j['status'],'new'); self.assertIsNone(j['score'])
            db.update_job(self.job.id,{'status':'filtered','score':20})
            self.assertEqual(db.query_jobs(),[])
        with scope(self.p['id']):
            self.assertEqual(db.get_job(self.job.id)['status'],'starred')
            self.assertEqual(db.get_job(self.job.id)['score'],90)

    def test_edit_resets_evaluation_preserves_manual_status(self):
        with scope(self.p['id']):
            db.upsert_jobs([self.job]);db.update_job(self.job.id,{'enriched':1,'score':99,'status':'applied','verdict':'recommend'})
            old=plans.get()['revision']
            save_settings({'criteria':{'keywords':['AI']}})
            j=db.get_job(self.job.id)
            self.assertEqual(j['enriched'],0);self.assertIsNone(j['score']);self.assertEqual(j['status'],'applied')
            db.update_evaluation(j['id'],{'score':88,'evaluated':1},old)
            self.assertIsNone(db.get_job(j['id'])['score'])
        self.assertEqual(plans.get(self.q['id'])['criteria']['keywords'],['销售'])

    def test_updates_existing_facts(self):
        with scope(self.p['id']):
            db.upsert_jobs([self.job]);db.update_job(self.job.id,{'enriched':1})
            self.job.salary='20-30K';self.job.description+='新增技能要求'
            db.upsert_jobs([self.job])
            j=db.get_job(self.job.id);self.assertEqual(j['salary'],'20-30K');self.assertEqual(j['enriched'],0)

    def test_cursor_covers_all_keywords(self):
        with scope(self.p['id']):
            self.assertEqual(plans.rotate('boss',list(range(7)),3),[0,1,2])
            self.assertEqual(plans.rotate('boss',list(range(7)),3),[3,4,5])
            self.assertEqual(plans.rotate('boss',list(range(7)),3),[6,0,1])
        with scope(self.q['id']): self.assertEqual(plans.rotate('boss',list(range(7)),3),[0,1,2])

    def test_soft_delete_restore_and_copy(self):
        with scope(self.p['id']): db.upsert_jobs([self.job])
        p2=plans.copy_plan(self.p['id'])
        with scope(p2['id']): self.assertEqual(db.query_jobs(),[])
        plans.update(self.p['id'],{'state':'deleted'})
        with self.assertRaises(ValueError): plans.get(self.p['id'])
        plans.update(self.p['id'],{'state':'active'})
        with scope(self.p['id']): self.assertEqual(len(db.query_jobs()),1)

    def test_filtered_candidates_saved(self):
        self.job.city='北京'
        with scope(self.p['id']), patch.object(execution.REGISTRY['boss'],'collect',AsyncMock(return_value=[self.job])):
            result=asyncio.run(execution.run_source('boss'))
            self.assertTrue(result['ok']);self.assertEqual(result['kept'],0)
            self.assertEqual(db.get_job(self.job.id)['status'],'filtered')
            self.assertIn('城市',db.get_job(self.job.id)['score_reason'])

    def test_missing_ai_item_retries_instead_of_marking_complete(self):
        save_global_settings({'llm':{'api_key':'test-only','enrich':True}})
        with scope(self.p['id']):
            db.upsert_jobs([self.job])
            with patch.object(llm,'enrich',AsyncMock(return_value=[])):
                asyncio.run(execution.enrich_pending())
            j=db.get_job(self.job.id);self.assertEqual(j['enriched'],0);self.assertEqual(j['attempts'],1)
        save_global_settings({'llm':{'api_key':''}})

    def test_unknown_date_cannot_be_confirmed_recommendation(self):
        save_global_settings({'llm':{'api_key':'test-only','enrich':True}})
        self.job.published_at=''
        with scope(self.p['id']):
            db.upsert_jobs([self.job])
            with patch.object(llm,'enrich',AsyncMock(return_value=[{'i':0,'verdict':'recommend','score':95,'reason':'相关','summary':'开发'}])):
                asyncio.run(execution.enrich_pending())
            self.assertEqual(db.get_job(self.job.id)['verdict'],'maybe')
        save_global_settings({'llm':{'api_key':''}})

    def test_proposal_bound_to_plan_and_version(self):
        from app import agent_tools
        with scope(self.p['id']): prop=agent_tools.propose({'keywords':['Agent']})
        with scope(self.q['id']): result=agent_tools.apply_proposal(prop['proposal_id'])
        self.assertEqual(result['plan_id'],self.p['id'])
        self.assertEqual(plans.get(self.p['id'])['criteria']['keywords'],['Agent'])
        self.assertEqual(plans.get(self.q['id'])['criteria']['keywords'],['销售'])
        with scope(self.p['id']): prop=agent_tools.propose({'keywords':['Go']})
        plans.update(self.p['id'],{'name':'改名'})
        with self.assertRaises(ValueError): agent_tools.apply_proposal(prop['proposal_id'])

    def test_boss_specific_detail_parser(self):
        from app.collectors.boss import parse_detail
        html='<html><div class="job-sec-text">负责 Python 服务开发</div><script type="application/ld+json">{"@type":"JobPosting","datePosted":"2026-10-24","employmentType":"FULL_TIME"}</script></html>'
        result=parse_detail(html)
        self.assertEqual(result['description'],'负责 Python 服务开发')
        self.assertEqual(result['published_at'],'2026-10-24')

    def test_boss_response_contract(self):
        from app.collectors.boss import classify
        self.assertEqual(classify({'code':0,'zpData':{}})[0],'error')
        self.assertEqual(classify({'code':0,'zpData':{'jobList':[]}})[0],'empty')
        self.assertEqual(classify({'code':0,'zpData':{'jobList':[{'salaryDesc':''}]}})[0],'ok')

    def test_boss_capture_ignores_wrong_query_and_page(self):
        from app.collectors.boss import _Capture,JOBLIST
        from types import SimpleNamespace
        async def check():
            page=SimpleNamespace(events=asyncio.Queue(),send=AsyncMock(return_value={'body':'{"code":0}'}))
            cap=_Capture(page);cap.expect('Python','101230200',2)
            for rid,query,number in [('wrong','Java',2),('old','Python',1),('right','Python',2)]:
                url=f'https://www.zhipin.com{JOBLIST}?query={query}&city=101230200&page={number}'
                request={'url':url} if rid!='right' else {'url':url.split('?')[0],'postData':f'query={query}&city=101230200&page={number}'}
                for method,params in [('Network.requestWillBeSent',{'requestId':rid,'request':request}),('Network.responseReceived',{'requestId':rid,'response':{'url':url}}),('Network.loadingFinished',{'requestId':rid})]:
                    page.events.put_nowait({'method':method,'params':params})
            self.assertEqual(await cap.next(1),{'code':0})
            page.send.assert_awaited_once_with('Network.getResponseBody',{'requestId':'right'})
        asyncio.run(check())

    def test_boss_checkpoint_and_detail_backoff(self):
        from app.collectors import boss_state as state
        with scope(self.p['id']):
            sig,start,head=state.page_start('Python','101230200')
            self.assertEqual(start,1)
            state.page_saved(sig,1,True)
            self.assertEqual(state.page_start('Python','101230200')[1],2)
            state.enqueue([self.job])
            self.assertEqual(len(state.pending(1)),1)
            state.detail_done(self.job.id,False,'没有正文')
            self.assertEqual(state.pending(1),[])
            row=db.conn().execute('SELECT * FROM boss_details WHERE job_id=?',(self.job.id,)).fetchone()
            self.assertEqual(row['attempts'],1)
        with scope(self.q['id']):
            self.assertEqual(state.page_start('Python','101230200')[1],1)
            self.assertEqual(state.pending(1),[])

    def test_boss_replay_does_not_move_checkpoint_backwards(self):
        from app.collectors import boss_state as state
        with scope(self.p['id']):
            sig,_,_=state.page_start('Python','101230200')
            state.page_saved(sig,4,True)
            state.page_saved(sig,1,True,head=True)
            self.assertEqual(state.page_start('Python','101230200')[1],5)

    def test_boss_ineligible_detail_does_not_use_budget(self):
        from app.collectors import boss_state as state
        with scope(self.p['id']):
            other=copy.deepcopy(self.job);other.external_id+='other';other.city='北京'
            state.enqueue([other,self.job])
            pending=state.pending(1,plans.get()['criteria'])
            self.assertEqual([job.id for job,_ in pending],[self.job.id])

    def test_job_type_from_detail_is_saved(self):
        with scope(self.p['id']):
            self.job.job_type=''
            db.upsert_jobs([self.job])
            self.job.job_type='fulltime'
            db.upsert_jobs([self.job])
            self.assertEqual(db.get_job(self.job.id)['job_type'],'fulltime')

    def test_boss_page_saved_before_later_timeout(self):
        from app.collectors import boss
        from contextlib import asynccontextmanager
        from types import SimpleNamespace
        @asynccontextmanager
        async def context(): yield SimpleNamespace(send=AsyncMock())
        data={'code':0,'zpData':{'jobList':[{'encryptJobId':'checkpoint-test','jobName':'Python','cityName':'厦门'}],'hasMore':True}}
        with scope(self.p['id']),patch.object(boss.browser,'browser_slot',context),patch.object(boss.browser,'CDPPage',context),patch.object(boss._Capture,'next',AsyncMock(side_effect=[data,None,None])),patch.object(boss,'_human_scroll',AsyncMock()),patch.object(boss.asyncio,'sleep',AsyncMock()):
            result=asyncio.run(execution.run_source('boss'))
            self.assertFalse(result['ok']);self.assertEqual(result['kind'],'coverage')
            self.assertEqual(result['added'],1)
            self.assertIsNotNone(db.get_job(boss.map_job(data['zpData']['jobList'][0]).id))

    def test_api_scope_crud_and_batch(self):
        from fastapi.testclient import TestClient
        from app.main import app
        client=TestClient(app)
        response=client.post('/api/plans/batch',json={'person':'小红','directions':['销售','策划'],'cities':['上海','厦门'],'criteria':{'job_types':['fulltime']}})
        self.assertEqual(response.status_code,200,response.text)
        ids=[p['id'] for p in response.json()];self.assertEqual(len(ids),4)
        headers={'X-Plan-ID':ids[0]}
        self.assertEqual(client.get('/api/settings',headers=headers).json()['criteria']['cities'],['上海'])
        self.assertEqual(client.get('/api/jobs',headers=headers).json()['jobs'],[])
        self.assertEqual(client.get('/api/overview',headers=headers).status_code,200)
        self.assertEqual(client.delete('/api/plans/'+ids[0],headers=headers).status_code,200)
        self.assertEqual(client.get('/api/jobs',headers=headers).status_code,404)
        self.assertEqual(client.patch('/api/plans/'+ids[0],headers=headers,json={'state':'active'}).status_code,200)

    def test_direct_trigger_respects_daily_cap(self):
        async def run():
            with scope(self.p['id']),patch.object(db,'runs_today',return_value=100):
                self.assertFalse(Scheduler().trigger('boss'))
        asyncio.run(run())

    def test_conductor_manages_explicit_target(self):
        with scope(self.p['id']):
            out=conductor.run('update_plan',{'plan_id':self.q['id'],'revision':self.q['revision'],'name':'上海策划'})
            self.assertEqual(out['plan']['name'],'上海策划')
            self.assertEqual(plans.get()['name'],'厦门 Python 全职')

if __name__=='__main__': unittest.main()

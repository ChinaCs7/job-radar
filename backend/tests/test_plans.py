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
    def test_browser_queue_does_not_spend_collection_budget(self):
        from app import browser,collection_budget
        async def check():
            lock=asyncio.Lock();await lock.acquire()
            async def release():
                await asyncio.sleep(.12);lock.release()
            task=asyncio.create_task(release())
            with patch.object(browser,'BROWSER_LOCK',lock),patch.object(browser,'GAP_SECONDS',(0,0)),patch.object(browser,'_last_release',0):
                async with asyncio.timeout(.06) as timer:
                    token=collection_budget.current_budget.set(collection_budget.Budget(timer))
                    try:
                        async with browser.browser_slot(): await asyncio.sleep(.01)
                    finally: collection_budget.current_budget.reset(token)
                self.assertFalse(lock.locked())
            await task
        asyncio.run(check())

    def test_cancelled_browser_waiter_does_not_release_owner(self):
        from app import browser
        async def check():
            lock=asyncio.Lock();await lock.acquire()
            with patch.object(browser,'BROWSER_LOCK',lock),patch.object(browser,'ACTIVE_TASK',('other','boss')):
                async def wait():
                    async with browser.browser_slot(): pass
                task=asyncio.create_task(wait());await asyncio.sleep(.01);task.cancel()
                await asyncio.gather(task,return_exceptions=True)
                self.assertTrue(lock.locked());self.assertEqual(browser.ACTIVE_TASK,('other','boss'))
                lock.release()
        asyncio.run(check())

    def test_collection_timeout_saves_partial_results(self):
        from app import collection_budget
        from app.collectors import REGISTRY
        async def collect(*args):
            rows=[];collection_budget.track(rows);rows.append(self.job)
            await asyncio.sleep(10)
        with scope(self.p['id']),patch.object(REGISTRY['boss'],'collect',new=collect),patch.object(collection_budget,'ACTIVE_SECONDS',.02):
            result=asyncio.run(execution.run_source('boss'))
            self.assertEqual(result['kind'],'timeout');self.assertEqual(result['found'],1)
            self.assertIsNotNone(db.get_job(self.job.id))

    def test_nowcoder_second_page_failure_preserves_first_page(self):
        from app.collectors.nowcoder import Nowcoder
        from app.collectors.base import CollectorError
        class Visit:
            last_response_meta={}
            title='职位搜索';final_url='https://www.nowcoder.com/jobs/fulltime/center'
            async def __aenter__(self): return self
            async def __aexit__(self,*args): pass
            next_json=AsyncMock(side_effect=[{'code':0},None])
            html=AsyncMock(return_value='<html></html>')
        with scope(self.p['id']),patch('app.collectors.nowcoder.browser.Visit',return_value=Visit()),patch('app.collectors.nowcoder.verified_jobs',return_value=([self.job],2)),patch('app.collectors.job51.next_page',new=AsyncMock(return_value=True)),patch('asyncio.sleep',new=AsyncMock()):
            with self.assertRaises(CollectorError) as ctx:
                asyncio.run(Nowcoder().collect({'keywords':['Python'],'cities':['厦门'],'job_types':['fulltime']},{'max_pages':2},{}))
        self.assertEqual(ctx.exception.kind,'coverage')
        self.assertEqual(ctx.exception.partial,[self.job])

    def test_native_search_contracts_reject_wrong_query_city_page(self):
        from app.collectors.job51 import verified_jobs,search_url
        from app.collectors.base import CollectorError
        response={'resultbody':{'job':{'items':[]}}}
        meta={'query':{'keyword':'Python','jobArea':'110300','pageNum':'2','sortType':'1'}}
        self.assertEqual(verified_jobs(response,meta,'Python','110300',2),[])
        for key in ('keyword','jobArea','pageNum','sortType'):
            bad=copy.deepcopy(meta);bad['query'][key]='wrong'
            with self.assertRaises(CollectorError): verified_jobs(response,bad,'Python','110300',2)
        self.assertEqual(search_url('Python','上海市')[1],'020000')
        with self.assertRaises(CollectorError): search_url('Python','不存在城市')

    def test_nowcoder_uses_creation_date_and_full_body(self):
        from app.collectors.nowcoder import verified_jobs
        from app.collectors.base import CollectorError
        meta={'body':{'query':'Python','jobCity':['厦门'],'recruitType':'3','page':'1'}}
        item={'id':12,'jobName':'Python开发','createTime':1577808000000,'refreshTime':1792800000000,
              'ext':json.dumps({'infos':'工作职责','requirements':'岗位要求'}),'recruitType':3,'jobCity':'厦门'}
        response={'code':0,'data':{'currentPage':1,'totalPage':2,'datas':[{'data':item}]}}
        jobs,total=verified_jobs(response,meta,'Python','厦门',3,1)
        self.assertEqual(total,2);self.assertEqual(jobs[0].description,'工作职责\n岗位要求')
        self.assertTrue(jobs[0].published_at.startswith('2020-01-01'))
        with self.assertRaises(CollectorError): verified_jobs(response,meta,'Python','厦门',3,2)
        with self.assertRaises(CollectorError): verified_jobs(response,meta,'Python','上海',3,1)

    def test_zhilian_does_not_accept_nationwide_for_city(self):
        from app.collectors.webpages import verified_zhilian
        from app.collectors.base import CollectorError
        state={'queryParams':{'kw':'Python','jl':'682'},'positionList':[]}
        html='<script>window.__INITIAL_STATE__='+json.dumps(state)+'</script>'
        self.assertEqual(verified_zhilian(html,'Python',{'cities':['厦门']}),[])
        with self.assertRaises(CollectorError): verified_zhilian(html.replace('682','489'),'Python',{'cities':['厦门']})

    def test_harvest_context_stays_inside_result_card(self):
        from app.collectors.webpages import harvest
        html='<div><div class="card"><a href="/jobs/1">A</a>甲公司</div><div class="card"><a href="/jobs/2">B</a>乙公司</div></div>'
        jobs=harvest(html,'https://example.com',r'/jobs/',container_xpath='//div[@class="card"]')
        self.assertEqual(len(jobs),2)
        self.assertNotIn('乙',jobs[0][2]);self.assertNotIn('甲',jobs[1][2])

    def test_search_budget_rotates_cities_and_sites(self):
        from app.collectors.websearch import search_queries
        queries=search_queries({'keywords':['销售','策划'],'cities':['上海','厦门']},['nowcoder.com'])
        self.assertEqual(len(queries),8)
        self.assertTrue(all(not ('上海' in q and '厦门' in q) for q in queries))
        with scope(self.p['id']):
            first=plans.rotate('bing',queries,3);second=plans.rotate('bing',queries,3);third=plans.rotate('bing',queries,3)
        self.assertEqual(set(first+second+third),set(queries))

    def test_company_partial_failure_keeps_successes(self):
        from app.collectors.companies import Companies
        from app.collectors.base import CollectorError
        cfg={'companies':[{'name':'有效公司','type':'tencent'},{'name':'不支持公司','type':'unknown'}]}
        with patch.object(Companies,'_tencent',new=AsyncMock(return_value=[self.job])),patch('app.collectors.companies.asyncio.sleep',new=AsyncMock()):
            with self.assertRaises(CollectorError) as ctx:
                asyncio.run(Companies().collect({'keywords':['Python']},cfg,{}))
        self.assertEqual(ctx.exception.kind,'partial');self.assertEqual(ctx.exception.partial,[self.job])

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

    def test_maimai_structured_posts_preserve_date_and_exclude_account_data(self):
        from app.collectors.maimai import initial_data,parse_posts
        data={'keyword':'Python 招聘','type':'gossip','gossips':[{'gossip':{'id':'123','egid':'public-post-id','text':'招聘 Python 工程师\n负责后台服务。','crtime':'2026-10-20 12:30:00'}}],'more':0}
        html='<script>share_data = JSON.parse('+json.dumps(json.dumps({'data':data,'auth_info':{'token':'must-not-persist'}}))+');</script>'
        jobs=parse_posts(initial_data(html,'Python 招聘'))
        self.assertEqual(jobs[0].external_id,'123')
        self.assertEqual(jobs[0].published_at,'2026-10-20 12:30:00')
        self.assertIn('gid=123',jobs[0].url)
        self.assertNotIn('must-not-persist',repr(jobs))
        with self.assertRaises(execution.CollectorError): initial_data(html,'Java 招聘')

    def test_maimai_missing_list_is_not_empty_success(self):
        from app.collectors.maimai import parse_posts
        with self.assertRaises(execution.CollectorError): parse_posts({'error':'login'})
        self.assertEqual(parse_posts({'gossips':[]}),[])

    def test_liepin_city_and_page_are_explicit(self):
        from app.collectors.liepin import search_url
        from urllib.parse import urlparse,parse_qs
        url,code=search_url('Python','厦门市',1)
        self.assertEqual(code,'090040')
        self.assertEqual(parse_qs(urlparse(url).query)['currentPage'],['1'])
        with self.assertRaises(execution.CollectorError): search_url('Python','不存在的城市',0)

    def test_liepin_rejects_nationwide_and_wrong_page(self):
        from app.collectors.liepin import verified_jobs
        response={'data':{'data':{'jobCardList':[],'jobSubscribeInfo':{'keyword':'Python','dqCode':'410'}},'pagination':{'currentPage':0}}}
        with self.assertRaises(execution.CollectorError): verified_jobs(response,'Python','090040',0)
        response['data']['data']['jobSubscribeInfo']['dqCode']='090040'
        with self.assertRaises(execution.CollectorError): verified_jobs(response,'Python','090040',1)
        self.assertEqual(verified_jobs(response,'Python','090040',0)[0],[])
        self.assertIsNone(verified_jobs({'data':{'pubTimes':[]}},'Python','090040',0))

    def test_browser_capture_metadata_excludes_tokens(self):
        from app.browser import Visit
        from types import SimpleNamespace
        async def check():
            visit=Visit('https://example.test',capture='/search/gossips')
            visit.page=SimpleNamespace(events=asyncio.Queue(),send=AsyncMock(return_value={'body':'{"data":{}}'}))
            visit.page.events.put_nowait({'method':'Network.responseReceived','params':{'requestId':'1','response':{'url':'https://example.test/search/gossips?query=Python&offset=20&sortby=time&token=secret'}}})
            visit.page.events.put_nowait({'method':'Network.loadingFinished','params':{'requestId':'1'}})
            task=asyncio.create_task(visit._watch())
            try:
                self.assertEqual(await visit.next_json(1),{'data':{}})
                self.assertEqual(visit.last_response_meta['query'],{'query':'Python','offset':'20','sortby':'time'})
            finally:
                task.cancel();await asyncio.gather(task,return_exceptions=True)
        asyncio.run(check())

    def test_maimai_seeking_and_old_posts_filtered_before_ai(self):
        from app.collectors.maimai import parse_posts
        jobs=parse_posts({'gossips':[{'gossip':{'id':'seeking','text':'求内推，Python 开发','crtime':'2026-10-24 12:00:00'}},{'gossip':{'id':'old','text':'招聘 Python 开发','crtime':'2020-10-24 12:00:00'}}]})
        with scope(self.p['id']),patch.object(execution.REGISTRY['maimai'],'collect',AsyncMock(return_value=jobs)):
            result=asyncio.run(execution.run_source('maimai'))
            self.assertEqual(result['kept'],0)
            self.assertEqual(db.jobs_to_enrich(),[])

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

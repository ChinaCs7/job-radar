"""Bounded domain tools for the conductor: no arbitrary shell/browser execution."""
from . import plans, db
from .plan_context import scope, current_plan

def function(name,description,properties,required=()):
    return {'type':'function','function':{'name':name,'description':description,
        'parameters':{'type':'object','properties':properties,'required':list(required),'additionalProperties':False}}}

TEXT={'type':'string'}
STRINGS={'type':'array','items':TEXT}
CRITERIA={'type':'object','additionalProperties':False,'properties':{
    'keywords':STRINGS,'cities':STRINGS,'job_types':{'type':'array','items':{'type':'string','enum':['fulltime','parttime','intern','contract']}},
    'exclude':STRINGS,'profile':TEXT,'salary_min_k':{'type':'number','minimum':0},'max_age_days':{'type':'integer','minimum':0,'maximum':365},
    'regions':{'type':'object','properties':{k:{'type':'boolean'} for k in ('domestic','overseas','remote')},'additionalProperties':False}}}
TOOLS=[
    function('preview_search_plans','根据简历证据和用户意向生成独立方案预览，不写入数据库。代码会把 directions × cities 组合；方向名称不得包含城市。例：销售/策划 × 上海/厦门，只传两个 directions、两个 cities，返回四条。未知城市、薪资写入 questions。设计/建议请求先用此工具；用户明确要求创建后再 create_plan。',{
        'person':TEXT,'profile':TEXT,'directions':{'type':'array','minItems':1,'maxItems':6,'items':{'type':'object','additionalProperties':False,
            'properties':{'name':TEXT,'keywords':STRINGS,'reason':TEXT,'evidence':STRINGS},'required':['name','keywords','reason','evidence']}},
        'cities':STRINGS,'job_types':{'type':'array','items':{'type':'string','enum':['fulltime','parttime','intern','contract']}},
        'remote_only':{'type':'boolean'},'salary_min_k':{'type':'number','minimum':0},'questions':STRINGS},
        ['person','profile','directions','cities','job_types','questions']),
    function('list_plans','列出所有求职者的方案概览，包括 ID、名称、关键词、城市、类型、版本、状态和数量；不加载简历简介。需要完整条件再 get_plan。管理前先查，不要猜 ID。',{}),
    function('get_plan','读取指定方案的完整条件和版本号。编辑前调用。',{'plan_id':TEXT},['plan_id']),
    function('create_plan','用户明确要求创建时，创建一个独立方案，不自动检索。不同城市或方向需要独立比较时分别创建；新方案不继承其他人的简介。',
        {'name':TEXT,'person':TEXT,'criteria':CRITERIA},['name','person','criteria']),
    function('update_plan','按用户明确要求编辑指定方案。先读取版本号；修改条件会重新评估该方案的旧候选。保留用户未要求变更的字段。',
        {'plan_id':TEXT,'revision':{'type':'integer'},'name':TEXT,'person':TEXT,'criteria':CRITERIA,
         'sources':{'type':'object','description':'平台 ID 到配置对象的映射；enabled 开关，interval_min 检索间隔。先 plan_progress 查看现有配置。'},
         'running':{'type':'boolean'}},['plan_id','revision']),
    function('manage_plan','按用户明确要求归档、移入回收区或恢复方案。删除可恢复，不删除共享岗位。',
        {'plan_id':TEXT,'state':{'type':'string','enum':['active','archived','deleted']}},['plan_id','state']),
    function('run_plan','用户要求检索时启动指定方案，所有平台遵守统一预算和登录限制；返回实际启动的信源，不能据此说已找到岗位。',
        {'plan_id':TEXT,'source':TEXT},['plan_id']),
    function('cancel_plan','取消指定方案正在执行的采集任务，保留已经收集的岗位。',{'plan_id':TEXT},['plan_id']),
    function('plan_progress','查看方案各平台的实际进度、错误、最近检索、数量和筛选结果。',{'plan_id':TEXT},['plan_id']),
    function('search_plan_jobs','在指定方案的候选中查询，可包含被过滤的岗位，用于解释漏项。',
        {'plan_id':TEXT,'q':TEXT,'include_filtered':{'type':'boolean'}},['plan_id']),
]

def run(name,args):
    from .scheduler import scheduler
    if name=='preview_search_plans': return preview(args)
    if name=='list_plans':
        rows=[]
        for p in plans.listing(True):
            rows.append({**{k:p.get(k) for k in ('id','name','person','revision','state','running','candidates','recommended')},
                         'criteria':{k:p['criteria'].get(k) for k in ('keywords','cities','job_types')}})
        return {'plans':rows,'current_plan_id':current_plan.get(),'notice':'这是方案概览，完整条件和简介用 get_plan 按需读取'}
    if name=='get_plan': return plans.get(args['plan_id'],True)
    if name=='create_plan': return {'ok':True,'plan':plans.create(args)}
    pid=args.get('plan_id')
    if not pid: raise ValueError('请指定方案 ID')
    if name=='update_plan':
        out=plans.update(pid,{k:v for k,v in args.items() if k!='plan_id'})
        scheduler.cancel(pid)
        return {'ok':True,'plan':out}
    if name=='manage_plan':
        out=plans.update(pid,{'state':args['state'],'running':False})
        scheduler.cancel(pid)
        return {'ok':True,'plan':out}
    if name=='cancel_plan': return {'cancelled':scheduler.cancel(pid)}
    plans.get(pid)
    with scope(pid):
        if name=='run_plan':
            sid=args.get('source')
            if sid:
                from .collectors import REGISTRY
                if sid not in REGISTRY: raise ValueError('未知信源')
                return {'started':[sid] if scheduler.trigger(sid) else []}
            return {'started':scheduler.run_all_now()}
        if name=='plan_progress': return {'sources':list(scheduler.status().values()),'stats':db.job_stats()}
        if name=='search_plan_jobs':
            statuses=['new','seen','starred','applied','dismissed','filtered'] if args.get('include_filtered') else None
            rows=db.query_jobs(q=args.get('q') or '',statuses=statuses,limit=30)
            return {'count':len(rows),'jobs':[{k:j.get(k) for k in ('serial','title','company','city','status','verdict','verdict_reason','score_reason','url')} for j in rows]}
    raise ValueError('未知工具')


def preview(args):
    """The model proposes evidence and intent; code constructs executable combinations."""
    from .agent_tools import mask_contacts
    directions=args.get('directions') or []
    if not isinstance(directions,list) or not 1<=len(directions)<=6: raise ValueError('请给出 1–6 个求职方向')
    cities=args.get('cities') or []
    if not isinstance(cities,list) or any(not isinstance(c,str) for c in cities): raise ValueError('城市必须是文字列表')
    cities=list(dict.fromkeys(c.strip() for c in cities if c.strip()))
    if args.get('remote_only'): cities=[]
    if len(directions)*max(1,len(cities))>12: raise ValueError('一次最多预览 12 个方案，请缩小方向或城市范围')
    questions=args.get('questions') or []
    if not isinstance(questions,list) or any(not isinstance(q,str) for q in questions): raise ValueError('待确认项必须是文字列表')
    drafts=[]
    signatures=set()
    for direction in directions:
        if not isinstance(direction,dict) or not direction.get('name') or not direction.get('keywords'): raise ValueError('每个方向需要名称和搜索关键词')
        name=str(direction['name'])
        if any(name==city or any(name.startswith(city+sep) or name.endswith(sep+city) for sep in ('-','·',' / ',' ','—','：')) for city in cities):
            raise ValueError('directions 只传求职方向，不要把城市写进方向名称；销售/策划两个方向 × 上海/厦门两个城市由代码生成四个方案，请修正参数后重试')
        signature=tuple(sorted(str(k).strip().lower() for k in direction['keywords']))
        if signature in signatures: raise ValueError('出现关键词相同的重复方向，请合并方向后重试；城市会自动组合')
        signatures.add(signature)
        for city in cities or ['']:
            criteria=plans.clean_criteria({'keywords':direction['keywords'],'cities':[city] if city else [],
                'job_types':args.get('job_types') or [],'profile':mask_contacts(str(args.get('profile') or ''))[0],
                'salary_min_k':args.get('salary_min_k') or 0,'max_age_days':30,'exclude':[],
                'regions':{'domestic':not args.get('remote_only'),'overseas':False,'remote':bool(args.get('remote_only'))}})
            drafts.append({'name':str(direction['name'])+' · '+(city or ('远程' if args.get('remote_only') else '城市待确认')),
                'person':str(args.get('person') or '我'),'criteria':criteria,
                'reason':str(direction.get('reason') or '')[:1000],
                'evidence':[mask_contacts(str(e))[0][:500] for e in direction.get('evidence') or []][:6]})
    return {'ok':True,'drafts':drafts,'questions':questions,'saved':False,'notice':'仅为方案预览，尚未创建或检索；薪资 0 表示未设门槛，城市空表示未限定，不代表用户已确认'}

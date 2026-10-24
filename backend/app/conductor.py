"""Bounded domain tools for the conductor: no arbitrary shell/browser execution."""
from . import plans, db
from .plan_context import scope, current_plan

def function(name,description,properties,required=()):
    return {'type':'function','function':{'name':name,'description':description,
        'parameters':{'type':'object','properties':properties,'required':list(required),'additionalProperties':False}}}

TEXT={'type':'string'}
TOOLS=[
    function('list_plans','列出所有求职者的方案，包括方案 ID、名称、条件、状态和候选数量。管理方案前先查；不要猜 ID。',{}),
    function('get_plan','读取指定方案的完整条件和版本号。编辑前调用。',{'plan_id':TEXT},['plan_id']),
    function('create_plan','用户明确要求创建时，创建一个独立方案，不自动检索。不同城市或方向需要独立比较时分别创建；新方案不继承其他人的简介。',
        {'name':TEXT,'person':TEXT,'criteria':{'type':'object','description':'keywords/cities/job_types/exclude 为数组；regions 为 domestic/overseas/remote 布尔值；profile 为脱敏能力简介；salary_min_k、max_age_days 为数字。'}},['name','person','criteria']),
    function('update_plan','按用户明确要求编辑指定方案。先读取版本号；修改条件会重新评估该方案的旧候选。保留用户未要求变更的字段。',
        {'plan_id':TEXT,'revision':{'type':'integer'},'name':TEXT,'person':TEXT,'criteria':{'type':'object'},
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
    if name=='list_plans': return {'plans':plans.listing(True),'current_plan_id':current_plan.get()}
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

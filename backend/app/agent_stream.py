"""Visible Agent loop: stream user-facing text and tool lifecycle events.

Reasoning and partial tool arguments stay inside the runtime. Only fully assembled
tool calls execute, and duplicate mutations within a turn reuse their first result.
"""
import asyncio
import json
import time
import uuid
import httpx
from . import db, llm, plans
from .agent_tools import mask_contacts


async def model_events(config,messages):
    if not config.get('api_key'): raise llm.LLMError('Agent 是可选 AI 功能，需要配置 key；基础检索照常可用')
    body={'model':config.get('model') or 'deepseek-flash','messages':messages,'tools':llm.TOOLS,
          'thinking':{'type':'disabled'},'stream':True,'stream_options':{'include_usage':True}}
    content=[];reasoning=[];calls={};usage=None;received=False;finished=False
    async with httpx.AsyncClient(timeout=90) as client:
        async with client.stream('POST',config['base_url'].rstrip('/')+'/chat/completions',
                headers={'Authorization':'Bearer '+config['api_key']},json=body) as response:
            if response.status_code>=400:
                raise llm.LLMError({401:'AI key 无效',402:'AI 账户余额不足'}.get(response.status_code,f'AI 服务返回 {response.status_code}'))
            try:
                async for line in response.aiter_lines():
                    if not line.startswith('data:'): continue
                    raw=line[5:].strip()
                    if raw=='[DONE]': break
                    if not raw: continue
                    packet=json.loads(raw);received=True
                    if packet.get('error'): raise llm.LLMError('AI 服务中断了回复，请查看已完成的工具步骤')
                    if packet.get('usage'): usage=packet['usage']
                    for choice in packet.get('choices') or []:
                        if choice.get('finish_reason'):
                            if choice['finish_reason'] not in ('stop','tool_calls'): raise llm.LLMError('AI 回复因长度或服务限制中断，尚未完成')
                            finished=True
                        delta=choice.get('delta') or {}
                        if delta.get('reasoning_content'): reasoning.append(delta['reasoning_content'])
                        if delta.get('content'):
                            content.append(delta['content']);yield {'type':'delta','text':delta['content']}
                        for part in delta.get('tool_calls') or []:
                            index=part['index'];call=calls.setdefault(index,{'id':'','type':'function','function':{'name':'','arguments':''}})
                            if part.get('id'): call['id']=part['id']
                            for key in ('name','arguments'):
                                call['function'][key]+=(part.get('function') or {}).get(key) or ''
                            if len(call['function']['arguments'])>30000: raise llm.LLMError('工具参数超过本轮限制')
                if not finished: raise llm.LLMError('AI 回复连接提前结束，未执行未完成的工具调用')
            finally:
                if received: llm.record_usage(config,'assistant',usage)
    message={'role':'assistant','content':''.join(content)}
    if calls: message['tool_calls']=[calls[i] for i in sorted(calls)]
    if reasoning: message['reasoning_content']=''.join(reasoning)
    yield {'type':'message','message':message}


def build_messages(criteria,history):
    messages=[{'role':'system','content':llm.ASSISTANT_SYSTEM.format(criteria=llm._criteria_text(criteria))+
               '\n当前方案 ID：'+plans.get()['id']}]
    for row in history[-20:]:
        if row.get('role') not in ('user','assistant') or not isinstance(row.get('content'),str): continue
        text=mask_contacts(row['content'][:18000])[0]
        if len(row['content'])>18000: text+='\n[本条内容超过上下文预算，后续部分未载入；请勿假设已读完]'
        messages.append({'role':row['role'],'content':text})
    if not messages or messages[-1]['role']!='user': raise ValueError('请先输入需求')
    return messages


async def events(config,criteria,history):
    run_id=uuid.uuid4().hex;steps=[];proposals=[];memo={};tool_count=0
    db.log('info',f'Agent {run_id}：开始本轮对话','agent')
    yield {'type':'start','run_id':run_id}
    try:
        messages=build_messages(criteria,history)
        async with asyncio.timeout(240):
            for turn in range(8):
                yield {'type':'status','message':'正在整理回复' if turn else '正在理解需求'}
                message=None
                async for event in model_events(config,messages):
                    if event['type']=='message': message=event['message']
                    else: yield event
                if message is None: raise llm.LLMError('模型未返回完整消息')
                calls=message.get('tool_calls') or []
                if not calls:
                    db.log('info',f'Agent {run_id}：完成，调用 {len(steps)} 个工具','agent')
                    yield {'type':'done','run_id':run_id,'steps':steps,'proposals':proposals};return
                messages.append(message)
                if message.get('content'): yield {'type':'delta','text':'\n\n'}
                for call in calls:
                    tool_count+=1
                    if tool_count>24: raise llm.LLMError('本轮达到 24 次工具调用限制，请缩小目标；已执行的操作保留')
                    name=call.get('function',{}).get('name','');call_id=call.get('id') or uuid.uuid4().hex
                    start=time.monotonic()
                    yield {'type':'tool_start','id':call_id,'tool':name}
                    try:
                        if name not in {t['function']['name'] for t in llm.TOOLS}: raise ValueError('没有这个工具')
                        args=json.loads(call['function'].get('arguments') or '{}')
                        if not isinstance(args,dict): raise ValueError('工具参数必须是对象')
                        signature=json.dumps([name,args],sort_keys=True,ensure_ascii=False)
                        if signature in memo: result=memo[signature]
                        else:
                            result=llm.run_tool(name,args)
                            # Failed calls can be corrected; successful mutations must not repeat.
                            if name in ('create_plan','update_plan','manage_plan','run_plan','propose_settings') and not result.get('error'):
                                memo[signature]=result
                    except (ValueError,KeyError,TypeError) as error:
                        result={'ok':False,'error':str(error)}
                    ok=not result.get('error') and result.get('ok') is not False
                    step={'id':call_id,'tool':name,'args':{},'count':result.get('count'),'status':'done' if ok else 'error','message':result.get('error',''),'elapsed_ms':round((time.monotonic()-start)*1000)}
                    steps.append(step);yield {'type':'tool_end',**step}
                    db.log('info' if ok else 'warn',f'Agent {run_id}：{name} {step["status"]}，{step["elapsed_ms"]}ms'+('；'+mask_contacts(str(result.get('error')))[0][:200] if not ok else ''),'agent')
                    if name=='preview_search_plans' and ok:
                        yield {'type':'plan_preview','drafts':result['drafts'],'questions':result.get('questions',[])}
                    if name=='propose_settings' and ok:
                        proposal={k:result[k] for k in ('proposal_id','changes','enable_sources','disable_sources','reason')}
                        proposals.append(proposal);yield {'type':'proposal','proposal':proposal}
                    encoded=json.dumps(result,ensure_ascii=False,default=str)
                    if len(encoded)>16000:
                        encoded=json.dumps({'truncated':True,'notice':'工具结果超过上下文预算，请缩小查询；以下为开头片段','excerpt':encoded[:15000]},ensure_ascii=False)
                    messages.append({'role':'tool','tool_call_id':call_id,'content':encoded})
            raise llm.LLMError('本轮达到 8 轮处理限制；已执行的操作保留，请继续指定下一步')
    except asyncio.CancelledError:
        db.log('info',f'Agent {run_id}：回复停止或连接断开，已完成操作保留','agent')
        raise
    except Exception as error:
        message=str(error) if isinstance(error,(ValueError,llm.LLMError)) else 'Agent 本轮中断，请查看已完成的步骤；已执行的方案操作不会自动撤销'
        if isinstance(error,asyncio.TimeoutError): message='Agent 本轮达到 4 分钟时限；已执行的方案操作保留'
        db.log('warn',f'Agent {run_id}：{message}','agent')
        yield {'type':'error','message':message,'run_id':run_id}

"""Render the saved 2026-10-30 study; does not select or rerun candidates."""
from pathlib import Path
import csv, html, json

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'results/evolution_20261030'
def read(name):return json.loads((OUT/name).read_text())
state=read('state.json');final=read('final.json');protocol=read('protocol.json')
names={'reversal5':'五日反转','momentum20':'20日动量','breakout20':'20日突破','amount20':'成交额放大','lowvol20':'20日低波动',
       'reversal10':'十日反转','reversal5_vol20':'波动率标准化反转','momentum60':'60日动量','lowvol60':'60日低波动',
       'reversal5_smooth3':'平滑反转','reversal_lowvol_half':'反转＋低波动秩混合','seed_ensemble':'初始五因子等权组合','evolved_ensemble':'冻结的多样化因子组合'}
blocks=[];md=[]
def paragraph(text):blocks.append('<p>'+html.escape(text)+'</p>');md.append(text+'\n')
def title(text):blocks.append('<h2>'+html.escape(text)+'</h2>');md.append('## '+text+'\n')
def table(headers,rows):
    blocks.append('<div class="scroll"><table><thead><tr>'+''.join('<th>'+html.escape(str(x))+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(x))+'</td>' for x in row)+'</tr>' for row in rows)+'</tbody></table></div>')
    md.append('| '+' | '.join(headers)+' |\n| '+' | '.join(['---']*len(headers))+' |\n'+'\n'.join('| '+' | '.join(str(x).replace('|','/') for x in row)+' |' for row in rows)+'\n')
def pct(v):return f'{v:.2%}'
paragraph('穿石实验室 · 因子演化研究 · 2026年10月30日')
paragraph('本轮以5个起点开展2轮、6个新增候选的实际研究。当前聊天中的Agent读取每轮实测反馈并提出下一轮候选，本机运行评价。模型权重固定，没有调用独立模型API，也未实现无人值守的自动生成器。')
paragraph('搜索区间：2024-01-02至2025-12-31。检查区间：2026年首个交易日至2026-09-30。两段均为已有历史；2026结果在本轮选型冻结后才计算，但不是全新盲测。输入5,451列证券，按逐日历史ST、交易状态和已有资格规则筛选。')
title('本轮发现')
paragraph('没有新增候选同时提高相对父因子的预测相关性和正IC月份比例，并达到最终组合资格。60日动量通过了相对改进门槛，但搜索期IC仍为负，未进入投资组合。反转与低波动的秩混合提高平均IC，却因月度稳定性不及父因子而被拒绝。')
paragraph('最终按事先规则保留不同家族的五日反转与20日低波动，并以每日合格股票横截面百分位等权合成。初始五因子组合另作对照；它包含两个趋势因子和搜索期负IC因子，是未筛选基线，不代表最强现有组合。')
paragraph('2026年检查中，冻结组合的Rank IC为0.04084，高于初始五因子组合0.00226，但低于单独低波动的0.05136；冻结组合仅4/9个月IC为正，Q5−Q1平均5日报价收益为-0.10860%。本轮不能据此宣称稳定预测优势或盈利改善。组合来自已有因子的筛选，没有新增候选进入最终组合。')
title('全部搜索结果')
rows=[];export=[]
for key,item in state['candidates'].items():
    s=item['search'];status='基线' if item['round']==0 else ('接受相对改进' if item['accepted'] else '拒绝')
    rows.append([item['round'],names[key],names.get(item['spec'].get('parent'),'—'),f"{s['rank_ic']:.5f}",pct(s['positive_months']),status,'；'.join(item['reasons'])])
    export.append({'key':key,'round':item['round'],'parent':item['spec'].get('parent'),'family':item['spec']['family'],'formula':item['spec']['formula'],**s,'accepted':item['accepted'],'reasons':'；'.join(item['reasons'])})
table(['轮次','因子','父因子','平均Rank IC','正IC月份','结果','理由'],rows)
with (OUT/'candidates.csv').open('w',newline='',encoding='utf-8-sig') as f:
    w=csv.DictWriter(f,fieldnames=list(export[0]));w.writeheader();w.writerows(export)
title('多样性与冻结记录')
paragraph('冻结时间：'+final['frozen']['frozen_at']+'。单因子主方案：'+names[final['frozen']['primary_single']]+'。组合成员：'+'、'.join(names[k] for k in final['frozen']['members'])+'。')
for k,peers in final['frozen']['correlations'].items():
    for peer,rho in peers.items():paragraph(names[k]+'与'+names[peer]+'的搜索期平均绝对每日秩相关：'+f'{rho:.4f}'+'，门槛0.8。该门槛用于工程去重，不代表因子统计独立。')
paragraph('因子池按正向IC、至少一半月份IC为正、每家族最多一个及相关性筛选；等权组合不拟合收益权重。全部成员都有值的股票才获得组合分数，未按未来收益筛股票。组合成员和单因子主方案不根据2026结果重新选择。')
title('冻结后2026年回顾性检查')
table(['方案','5日Rank IC','正IC月份','Q5−Q1平均5日报价收益'],[[names[k],f"{x['rank_ic']:.5f}",pct(x['positive_months']),pct(x['spread'])] for k,x in final['diagnostics'].items()])
paragraph('以上是报价统计。分组收益未扣费，多日标签重叠，不累乘为净值，不等于实际成交收益。')
title('统一交易回测')
table(['方案','成本','累计收益','年化收益','最大回撤','夏普(无风险利率0)','单边换手倍数'],[[names[a['key']],'标准' if a['cost']=='normal' else '双倍',pct(a['metrics']['total_return']),pct(a['metrics']['annualized_return']),pct(a['metrics']['max_drawdown']),f"{a['metrics']['sharpe_zero_risk_free']:.3f}",f"{a['metrics']['turnover_one_way']:.2f}"] for a in final['accounts'] if 'metrics' in a])
blocked=[a for a in final['accounts'] if 'metrics' not in a]
if blocked:
    paragraph('交易评价尚不完整：以下账户因缺少持仓股票的已核验公司行为资料而停止。未用复权报价替代净交易结果，不能据此判断多因子组合是否改善扣费收益。')
    paragraph('补数尝试取得58个证券年份的公开响应，另有3个未取得；取得响应也不等于公司行为覆盖完整。低波动仍受000538、600572、600897、600900影响，初始组合受000538影响，冻结组合受601966影响。原始响应、获取时间及文件指纹保存在本机缓存和补数清单中。')
    table(['方案','成本','停止原因'],[[names[a['key']],a['cost'],a['error']] for a in blocked])
paragraph('各账户初始100万元、选最高分20只、总目标95%、每日调仓、收盘形成信号后次日尝试成交，期末按收盘估值且不强制清仓。使用原始股份PrecisionEngine及历史状态、容量与公司行为约束。标准佣金万三、最低5元、印花税万五、过户费十万分之一、滑点5bps。双倍成本同步加倍各项费用与滑点。')
title('Harness版本与真实反馈')
for n in [0,1,2]:
    request=read(f'round_{n}_request.json');paragraph(f"第{n}轮 · {request['harness']}：{request['feedback']}")
paragraph('H1修改的是候选生成提示与探索方向，评分器、数据范围与交易规则均未改变。本轮没有独立同预算Harness对照，不能把指标变化解释为Harness的因果提升。')
title('验证与复现')
paragraph('11个因子全部进行了截断未来数据后的前缀一致性检查。5个种子因子另与原接口在3个日期独立核对。因子模块23项现有测试通过；'+str(sum('metrics' in a for a in final['accounts']))+'个成功账户核对每日现金＋市值＋应收股利与权益及累计收益。未对新账户运行完整独立逐笔账本重放。')
paragraph('protocol.json保存搜索前规则；state.json与round_*_request.json保存全部尝试和反馈；frozen.json保存选型；search/和review/保存完整每日、月份与分组统计；accounts/保存权益、订单、持仓、信号与公司行为。manifest.json保存行情与代码指纹。')
paragraph('复现顺序：使用项目现有运行环境，research_evolution.py init，然后依次search两个已保存的round请求文件，再freeze和final。初始化拒绝覆盖既有研究；复现应使用独立副本或新的输出目录，不能直接覆盖本结果。候选矩阵和Panel缓存位于本机临时目录，不随结果分发。')
paragraph('复现使用保存的round_1_request.json和round_2_request.json，它们包含实际候选与当时反馈。该流程重放已经做出的研究决定，不会重新请求Agent生成新候选。data/evolution_actions中的补充资料由load_panel读取；缺少该资料时可能出现更多被阻止账户。')
paragraph('数据边界：课程证券名单未证明覆盖完整历史市场；历史ST按有效日而非公告时点处理；行业、市值与完整退市资料不足；日线成交仍是模拟。本轮完整结果用于研究，不证明未来可盈利。')
(OUT/'REPORT.md').write_text('# 穿石因子演化研究\n\n'+'\n'.join(md),encoding='utf-8')
css='body{font:16px/1.7 system-ui,sans-serif;color:#20352d;background:#faf8f1;margin:0}main{max-width:1200px;margin:auto;padding:36px}h1,h2{color:#175b42}h2{margin-top:36px}table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:10px;border-bottom:1px solid #d8dfd7;vertical-align:top}th{background:#e8eee6}.scroll{overflow:auto}p{max-width:1050px}a{color:#175b42}'
(OUT/'report.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>穿石 · 因子演化研究</title><style>'+css+'</style><main><h1>因子演化与多样化组合</h1>'+''.join(blocks)+'</main></html>',encoding='utf-8')
print(str(OUT/'report.html'))

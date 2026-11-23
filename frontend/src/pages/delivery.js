import {feedback} from '../components/common/fields.js';
import {metrics, panel, pill} from '../components/common/panels.js';
import {table} from '../components/common/table.js';
import {REVIEW} from '../constants/enums.js';
import {handler} from '../hooks/action.js';
import {session} from '../stores/session.js';
import {workspace} from '../stores/workspace.js';
import {button, el, link, p} from '../utils/dom.js';
import {date, value} from '../utils/format.js';
import {runPage} from './run.js';

function parsePackage(text) {
  let data;
  try { data = JSON.parse(text); }
  catch { throw new Error('交接包须为有效的 JSON 文件'); }
  if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('交接包须为 JSON 对象');
  return data;
}

function importPanel(message, refresh) {
  const submit = button('验算并接收', {type:'submit', class:'primary', 'data-testid':'import-handoff'});
  const form = el('form', {class:'fields', onSubmit:handler(submit, message, async event => {
    const data = new FormData(event.target);
    const file = data.get('package');
    const text = file?.size ? await file.text() : String(data.get('manifest') || '');
    if (!text.trim()) throw new Error('请选择交接包文件或粘贴 JSON 内容');
    const report = await workspace.importHandoff(parsePackage(text));
    if (report.state !== 'verified') {
      const reasons = report.result?.differences?.length ? `：${report.result.differences.join('；')}` : '。';
      message.textContent = `验算不一致，已退回${reasons}`;
      await refresh();
      return;
    }
    message.textContent = report.created ? '验算通过，已接收报告。' : '该交接包已验算过，未新增报告。';
    if (location.hash === `#delivery/${report.id}`) await refresh();
    else location.hash = `#delivery/${report.id}`;
  })},
  el('label', {class:'field', for:'handoff-package'}, el('span', {}, '交接包文件（JSON）'),
    el('input', {id:'handoff-package', name:'package', type:'file', accept:'.json,application/json'})),
  el('label', {class:'field', for:'handoff-manifest'}, el('span', {}, '或粘贴交接包 JSON'),
    el('textarea', {id:'handoff-manifest', name:'manifest', rows:6, maxlength:1_000_000})),
  submit);
  const sample = button('下载示例交接包', {class:'quiet'});
  sample.addEventListener('click', handler(sample, message, () => workspace.handoffTemplate()));
  const description = p(
    '交接包须带上原巡检、参数与规则版本。本站按声明版本原样重算，排名或命中单号不符即退回；'
    + '同批次只存一份，同站同号内容有变也退回。', 'subtle');
  return panel('接收外站交接包', description,
    session.canWrite ? el('div', {}, form, sample) : p('只读角色可以查看已验算报告。', 'subtle'), message);
}

function hitList(title, ids) {
  return panel(title,
    ids.length
      ? el('p', {}, `${ids.length} 条命中：${ids.join('、')}`)
      : p('本站重算在该组无命中。', 'subtle'));
}

async function reportDetail(route, catalog) {
  const item = await workspace.handoffReport(route.id);
  const labels = new Map(catalog.map(entry => [entry.version, entry.label]));
  const result = item.result;
  const ranking = table([
    {label:'名次', render:row=>row.rank},
    {key:'conditions', label:'伴随条件'},
    {key:'positive_count', label:'正组命中'},
    {key:'negative_count', label:'负组命中'},
    {label:'增长倍数', render:row=>value(row.growth)},
  ], result.ranking, {caption:'按原规则版本重算的排名', empty:'原巡检中没有达到门槛的模式。'});
  const params = Object.entries(item.params || {}).map(([key, entry]) =>
    el('div', {}, el('dt', {}, key), el('dd', {}, value(entry))));
  return el('div', {},
    panel(`交接报告 ${item.station} · ${item.report_no}`,
      el('div', {class:'actions'}, pill('验算通过', 'accepted'),
        link('返回交接列表', '#delivery', {class:'quiet'})),
      p(item.headline, 'intro-copy'),
      metrics([
        {label:'规则版本', value:`${item.rule_version}（${labels.get(item.rule_version) || '未登记'}）`},
        {label:'见霉斑巡检', value:result.positive_total},
        {label:'未见霉斑巡检', value:result.negative_total},
        {label:'接收时间', value:date(item.created_at)},
      ]),
      el('dl', {class:'dictionary'}, params)),
    panel('两组命中单号', p('按交接包声明的规则版本重算，可与原报告的命中单号逐条核对。', 'subtle'),
      hitList(`见霉斑组命中（${result.positive_total} 条巡检）`, result.positive_hits),
      hitList(`未见霉斑组命中（${result.negative_total} 条巡检）`, result.negative_hits)),
    panel('伴随模式排名', ranking));
}

function localExports(message) {
  const {spec, runs} = workspace;
  const rows = table([
    {label:'本站在此运行', render:row=>link(row.name, `#results/${row.id}`)},
    {label:'复核', render:row=>pill(REVIEW[row.review], row.review)},
    {label:'计算时间', render:row=>date(row.finished_at)},
    {label:'下载', render:row=>{
      const download = button('下载 CSV', {class:'quiet'});
      download.addEventListener('click', handler(download, message, () =>
        workspace.download(`/runs/${row.id}/export`, `${spec.short_name}-${row.id}.csv`)));
      return download;
    }},
  ], runs.filter(row => row.status === 'complete'), {caption:'本站运行结果', empty:'完成计算后会生成对应的报告。'});
  return panel('本站运行结果', p('这里只列本站自己运行生成的结果，与外站交接报告分开放置。', 'subtle'), rows);
}

export async function deliveryPage(route, refresh) {
  const {spec} = workspace;
  const message = feedback();
  const rules = await workspace.handoffRules();
  const reports = await workspace.handoffReports();
  if (route.id) return reportDetail(route, rules.versions);
  const versions = panel('规则版本登记',
    p(`当前本站规则为 ${rules.current}。旧交接包始终按其所声明的版本重算，不随本站升级改写。`, 'subtle'),
    table([
      {key:'version', label:'版本'},
      {key:'label', label:'名称'},
      {key:'released', label:'发布日期'},
      {key:'notes', label:'说明'},
    ], rules.versions, {caption:'规则版本登记'}));
  const verified = table([
    {label:'外站', key:'station'},
    {label:'报告号', render:row=>link(row.report_no, `#delivery/${row.id}`)},
    {label:'规则版本', render:row=>{
      const label = rules.versions.find(entry => entry.version === row.rule_version)?.label;
      return label ? `${row.rule_version} · ${label}` : row.rule_version;
    }},
    {label:'验算', render:()=>pill('验算通过', 'accepted')},
    {label:'接收时间', render:row=>date(row.created_at)},
  ], reports, {caption:'验算通过的交接报告', empty:'还没有验算通过的交接报告。'});
  const receipts = spec.scheduled ? panel('站内分发回执', table([
    {key:'recipient', label:'收件团队'},
    {label:'回执', render:row=>pill(row.state === 'delivered' ? '已投递' : '已拦截', row.state)},
    {key:'detail', label:'说明'}, {label:'时间', render:row=>date(row.created_at)},
    {label:'查看', render:row=>link(`运行 ${row.run_id}`, `#results/${row.run_id}`)},
  ], await workspace.deliveries(), {caption:'站内收件箱', empty:'计划到时执行，回执将在此更新。'})) : null;
  return el('div', {},
    el('div', {class:'two-col'},
      el('div', {class:'wide-panel'}, panel(spec.pages[5],
        p('这里只列出验算通过的外站报告。点击报告号可查看重算排名与两组命中单号。', 'subtle'),
        verified), localExports(message)),
      el('aside', {class:'sidebar-panel'}, versions, importPanel(message, refresh))),
    receipts, spec.scheduled && await runPage({...route, scheduling:true}, refresh));
}

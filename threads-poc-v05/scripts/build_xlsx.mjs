import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const data=JSON.parse(await fs.readFile(path.join(root,'output/threads_raw_v05.json'),'utf8'));
const st=data.validation.statistics;
const rows=data.normalized_records.filter(r=>r.content_type==='post' && ['direct','related'].includes(r.brand_relevance))
  .sort((a,b)=>(b.published_at_utc||'').localeCompare(a.published_at_utc||''));

function localExcelSerial(iso) {
  if (!iso) return null;
  // The ISO string already carries Taipei local components. Excel stores those components.
  const m=iso.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})/);
  if (!m || !iso.endsWith('+08:00')) throw Error('expected Asia/Taipei ISO time');
  const [,y,mo,d,h,mi,s]=m.map(Number);
  return (Date.UTC(y,mo-1,d,h,mi,s)-Date.UTC(1899,11,30))/86400000;
}
const heads=['發布時間（台灣）','貼文內容','品牌相關性','系統議題','系統情緒','情緒對象','疑似危機候選','複核優先級','複核原因','按讚數','回覆數','轉發數','引用數','熱度分數','原始貼文連結','來源平台','人工議題','人工情緒','人工情緒對象','人工危機候選','人工備註','複核狀態','record_id'];
const rel={direct:'直接相關',related:'間接相關',context_only:'背景',uncertain:'待確認',irrelevant:'無關'};
const values=rows.map(r=>[localExcelSerial(r.published_at_tw),r.text,rel[r.brand_relevance],r.topic_category,r.sentiment,r.sentiment_target,
  r.crisis_candidate,r.review_priority,r.review_reasons.join('；'),r.like_count,r.reply_count,r.repost_count,r.quote_count,
  r.heat_score===null?'不可計算':r.heat_score,r.source_url,'Threads',r.manual_topic,r.manual_sentiment,r.manual_sentiment_target,
  r.manual_crisis_candidate,r.manual_note,r.review_status,r.record_id]);
const wb=Workbook.create();
const sh=wb.worksheets.add('全聯輿情分析');
const summary=wb.worksheets.add('資料驗證摘要');
sh.getRangeByIndexes(0,0,values.length+1,heads.length).values=[heads,...values];
const end=values.length+1;
sh.getRange(`A1:W${end}`).format.font={name:'Arial',size:11,color:'#202B38'};
sh.getRange(`A1:W${end}`).format.verticalAlignment='center';
sh.getRange(`A1:W${end}`).format.wrapText=true;
sh.getRange(`A2:W${end}`).format.rowHeight=82;
sh.getRange('A1:W1').format={fill:'#24445B',font:{name:'Arial',size:11,color:'#FFFFFF',bold:true},rowHeight:34,wrapText:true};
sh.getRange('Q1:V1').format.fill='#546A3B';
const widths=[23,64,13,15,13,17,15,13,42,11,11,11,11,13,36,12,16,15,18,16,40,15,28];
for(let i=0;i<widths.length;i++) sh.getRangeByIndexes(0,i,end,1).format.columnWidth=widths[i];
sh.getRange(`A2:A${end}`).setNumberFormat('yyyy/mm/dd hh:mm');
sh.getRange(`J2:N${end}`).setNumberFormat('#,##0');
sh.getRange(`J2:N${end}`).format.horizontalAlignment='right';
sh.getRange(`Q2:V${end}`).format.fill='#F4F7ED';
sh.getRange(`O2:O${end}`).format.font={color:'#1558A0'};
const analysisTable=sh.tables.add(`A1:W${end}`,true,'QuanlianResearchV05');
analysisTable.style='TableStyleLight1';
analysisTable.showFilterButton=true;
sh.getRange(`H2:H${end}`).conditionalFormats.add('containsText',{text:'high',format:{fill:'#FCE4D6',font:{color:'#9C3313',bold:true}}});
sh.getRange(`H2:H${end}`).conditionalFormats.add('containsText',{text:'medium',format:{fill:'#FFF2CC',font:{color:'#775500'}}});
const lists={Q:['商品體驗','商品品質','價格與促銷','門市服務','品牌爭議','其他','待判定'],
  R:['positive','negative','neutral','mixed','uncertain'],S:['全聯','全聯商品','好市多','其他','unknown'],T:['yes','no','uncertain'],V:['pending','confirmed','corrected']};
for(const [col,options] of Object.entries(lists)) sh.getRange(`${col}2:${col}${end}`).dataValidation={rule:{type:'list',values:options}};
sh.freezePanes.freezeRows(1); sh.showGridLines=false;
const sm=[['項目','結果'],
 ['本次是否取得新全聯資料',st.new_unique_posts>0?'是':'否；公開搜尋權限／授權來源尚未具備'],
 ['本輪基準（Asia/Taipei）',localExcelSerial(st.reference_at_tw)],
 ['整理完成時間（Asia/Taipei）',localExcelSerial(new Date(Date.parse(data.processing_run.completed_at_utc)+8*3600000).toISOString().slice(0,19)+'+08:00')],
 ['新搜尋請求次數',st.search_request_count],['本次資料 API HTTP 請求次數',st.data_http_request_count],
 ['新搜尋原始結果筆數',st.live_returned_post_rows],['本次新增唯一全聯貼文數',st.new_unique_posts],
 ['總唯一全聯貼文數',st.total_unique_posts],['既有貼文數',st.legacy_posts],
 ['近 24h 新取得樣本數',st.newly_fetched_by_publication_time['24h']],['近 7d 新取得樣本數',st.newly_fetched_by_publication_time['7d']],['近 30d 新取得樣本數',st.newly_fetched_by_publication_time['30d']],
 ['舊樣本按發布時間落在近 24h',st.existing_by_publication_time['24h']],['舊樣本按發布時間落在近 7d',st.existing_by_publication_time['7d']],['舊樣本按發布時間落在近 30d',st.existing_by_publication_time['30d']],
 ['需要人工複核數',st.review_required_count],['人工確認／修正完成數',st.manually_confirmed_count],
 ['實際取得回覆全文紀錄數',st.observed_reply_records],['原貼文顯示 reply_count 合計',st.displayed_reply_count_sum],
 ['回覆有發布時間的比例',st.reply_timestamp_ratio===null?'N/A；沒有取得回覆':st.reply_timestamp_ratio],
 ['回覆有可確認父節點的比例',st.reply_confirmed_parent_ratio===null?'N/A；沒有取得回覆':st.reply_confirmed_parent_ratio],
 ['真正擷取時間已知的貼文數',st.actual_fetched_time_known],['互動快照保存方式',`${data.interaction_snapshots.length} 筆；舊樣本觀測時間 NULL，不估成長率`],
 ['工具 A', '0.1.1 CLI Help 已查；無 Recent/date CLI，含未驗證的 recent facet；最終依互動排序'],
 ['工具 B','只接受 top；GraphQL 最多 20 頁；本機 Go 1.19 低於需求 1.26，未建置／實搜'],
 ['Model A','PARTIAL：可人工標註，20 筆不足以驗證模型；規則分類非 Ground Truth'],
 ['Model B','BLOCKED：新資料、連續觀測、獨立事件、歷史互動快照不足'],
 ['Excel 時區與日期定義','數值為 Asia/Taipei wall-clock；顯示 yyyy/mm/dd hh:mm；輸出後重新解碼核對'],
 ['人工標註操作','綠色區輸入人工分類；明確執行匯入後保留歷史。系統欄位不會被人工值取代。'],
 ['取樣與熱度限制','皆為取得樣本，不代表 Threads 全平台聲量；熱度權重 1/3/4/2，缺值不可計算。'],
 ['下一步','App Dashboard 確認公開搜尋核准；或與教授申請 MCL Threads UI，另確認匯出與模型用途。']];
summary.getRangeByIndexes(0,0,sm.length,2).values=sm;
summary.getUsedRange().format={font:{name:'Arial',size:11,color:'#202B38'},wrapText:true,verticalAlignment:'center',rowHeight:34};
summary.getRange('A1:B1').format={fill:'#24445B',font:{name:'Arial',size:11,bold:true,color:'#FFFFFF'},rowHeight:30};
summary.getRange('B3:B4').setNumberFormat('yyyy/mm/dd hh:mm:ss');
summary.getRange(`A1:A${sm.length}`).format.columnWidth=34;
summary.getRange(`B1:B${sm.length}`).format.columnWidth=100;
summary.showGridLines=false;
await wb.recalculate();
const internal=path.join(root,'internal/workbook'); await fs.mkdir(internal,{recursive:true});
const result=await SpreadsheetFile.exportXlsx(wb); await result.save(path.join(internal,'threads_analysis_v05.xlsx'));
for (const [name,sheetName,range] of [['analysis_preview','全聯輿情分析','A1:I4'],['manual_preview','全聯輿情分析','O1:V4'],['summary_preview','資料驗證摘要','A1:B17']]) {
  try {const preview=await wb.render({sheetName,range,scale:1,format:'png'});
    await fs.writeFile(path.join(internal,name+'.png'),new Uint8Array(await preview.arrayBuffer()));
  } catch(error) {console.error('render_failed',name,String(error).slice(0,250)); process.exitCode=1;}
}
console.log(JSON.stringify({rows:rows.length,sheets:2,dates:'numeric Taipei wall-clock',saved:path.join(internal,'threads_analysis_v05.xlsx')}));
